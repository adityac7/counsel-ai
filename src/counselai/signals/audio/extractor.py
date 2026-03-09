"""Turn-aware audio signal extractor.

Refactors the legacy voice_analyzer into a structured pipeline that emits
per-turn and per-window audio features conforming to
``counselai.signals.audio.schemas``.

Pipeline stages:
  1. Load & validate audio (with ffmpeg fallback)
  2. Slice audio into per-turn segments using turn timestamps
  3. Extract per-turn features: pitch (pyin/parselmouth), energy (RMS),
     speech rate, pause detection, dysfluency markers
  4. Aggregate into topic-window summaries
  5. Compute session-level reliability score
  6. Optionally call Gemini for transcript-based dysfluency enrichment
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import re
import subprocess
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

import librosa
import numpy as np

from counselai.settings import settings
from counselai.signals.audio.schemas import (
    AudioFeatures,
    DysfluencyEvent,
    DysfluencyType,
    PauseEvent,
    TurnAudioFeatures,
    WindowAudioSummary,
)

logger = logging.getLogger(__name__)

# Try importing parselmouth for better pitch/voice-quality analysis.
try:
    import parselmouth
    from parselmouth.praat import call as praat_call

    _HAS_PARSELMOUTH = True
except ImportError:
    _HAS_PARSELMOUTH = False
    logger.info("parselmouth not installed — falling back to librosa-only pitch")


# ---------------------------------------------------------------------------
# Constants / tunables
# ---------------------------------------------------------------------------

_MIN_PAUSE_MS = 400  # Minimum silence to count as a pause
_LONG_PAUSE_MS = 2000  # "Long pause" threshold
_TOP_DB_SILENCE = 30  # librosa silence detection sensitivity
_PITCH_FMIN = 75  # Hz
_PITCH_FMAX = 500  # Hz
_HOP_LENGTH = 512
_FILLER_PATTERNS: list[str] = [
    "um", "uh", "uh huh", "like", "you know", "er", "ah",
    "hmm", "haan", "matlab", "wo", "basically", "actually",
]

# Gemini-based dysfluency prompt
_DYSFLUENCY_PROMPT = """\
You are a speech-language analysis system. Given a transcript turn from a \
counselling session, identify speech dysfluencies.

For each dysfluency found, return a JSON array of objects with:
- "type": one of "repetition", "false_start", "filler", "prolongation", "block"
- "text": the dysfluent segment
- "confidence": 0.0-1.0

If no dysfluencies, return an empty array [].

Transcript turn:
{text}
"""


# ---------------------------------------------------------------------------
# Audio loading helpers
# ---------------------------------------------------------------------------

def _find_ffmpeg() -> str:
    """Resolve ffmpeg binary."""
    candidates = [
        shutil.which("ffmpeg"),
        "/home/linuxbrew/.linuxbrew/bin/ffmpeg",
        "/usr/local/bin/ffmpeg",
        "/usr/bin/ffmpeg",
    ]
    for c in candidates:
        if c and os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    return ""


def _convert_to_wav(src: str) -> str | None:
    """Use ffmpeg to convert *src* to a .wav file, returning the new path."""
    ffmpeg = _find_ffmpeg()
    if not ffmpeg:
        logger.warning("ffmpeg not found — cannot convert %s", src)
        return None
    dst = os.path.splitext(src)[0] + ".extracted.wav"
    try:
        subprocess.run(
            [ffmpeg, "-y", "-i", src, "-ac", "1", "-ar", "16000", "-f", "wav", dst],
            capture_output=True,
            timeout=120,
            check=True,
        )
        return dst
    except Exception as exc:
        logger.warning("ffmpeg conversion failed for %s: %s", src, exc)
        return None


def load_audio(audio_path: str, sr: int | None = None) -> tuple[np.ndarray | None, int | None]:
    """Load audio with librosa; retry via ffmpeg WAV if first attempt fails."""
    if not os.path.exists(audio_path):
        logger.error("Audio file not found: %s", audio_path)
        return None, None
    if os.path.getsize(audio_path) == 0:
        logger.error("Audio file is empty: %s", audio_path)
        return None, None

    # Try direct load
    try:
        y, rate = librosa.load(audio_path, sr=sr)
        if y.size > 0:
            return y, rate
    except Exception as exc:
        logger.warning("Direct load failed (%s), trying ffmpeg fallback", exc)

    # Fallback: convert via ffmpeg
    wav_path = _convert_to_wav(audio_path)
    if wav_path and os.path.exists(wav_path):
        try:
            y, rate = librosa.load(wav_path, sr=sr)
            if y.size > 0:
                return y, rate
        except Exception as exc:
            logger.warning("Fallback load failed: %s", exc)

    return None, None


# ---------------------------------------------------------------------------
# Low-level feature helpers
# ---------------------------------------------------------------------------

def _detect_pauses_in_segment(
    y: np.ndarray, sr: int, offset_ms: int = 0
) -> list[PauseEvent]:
    """Detect silence gaps within an audio segment."""
    if y.size == 0:
        return []
    duration_ms = int(len(y) / sr * 1000)

    # Guard: if max amplitude is near-zero, treat entire segment as silence.
    # librosa.effects.split uses top_db relative to max, so all-zero signals
    # get treated as one big "voiced" interval — which is wrong for us.
    if np.max(np.abs(y)) < 1e-6:
        if duration_ms >= _MIN_PAUSE_MS:
            return [PauseEvent(
                start_ms=offset_ms,
                end_ms=offset_ms + duration_ms,
                duration_ms=duration_ms,
            )]
        return []

    nonsilent = librosa.effects.split(y, top_db=_TOP_DB_SILENCE)

    pauses: list[PauseEvent] = []
    last_end_ms = 0

    if nonsilent.size == 0:
        # Entire segment is silence
        if duration_ms >= _MIN_PAUSE_MS:
            pauses.append(PauseEvent(
                start_ms=offset_ms,
                end_ms=offset_ms + duration_ms,
                duration_ms=duration_ms,
            ))
        return pauses

    for interval in nonsilent:
        start_ms = int(interval[0] / sr * 1000)
        gap = start_ms - last_end_ms
        if gap >= _MIN_PAUSE_MS:
            pauses.append(PauseEvent(
                start_ms=offset_ms + last_end_ms,
                end_ms=offset_ms + start_ms,
                duration_ms=gap,
            ))
        last_end_ms = int(interval[1] / sr * 1000)

    # Trailing silence
    trailing = duration_ms - last_end_ms
    if trailing >= _MIN_PAUSE_MS:
        pauses.append(PauseEvent(
            start_ms=offset_ms + last_end_ms,
            end_ms=offset_ms + duration_ms,
            duration_ms=trailing,
        ))

    return pauses


def _pitch_stats_parselmouth(
    y: np.ndarray, sr: int
) -> tuple[float | None, float | None]:
    """Extract pitch mean and std using Praat via parselmouth."""
    if not _HAS_PARSELMOUTH:
        return None, None
    try:
        snd = parselmouth.Sound(y, sampling_frequency=sr)
        pitch = snd.to_pitch(time_step=0.01, pitch_floor=_PITCH_FMIN, pitch_ceiling=_PITCH_FMAX)
        f0 = pitch.selected_array["frequency"]
        f0_voiced = f0[f0 > 0]
        if f0_voiced.size == 0:
            return None, None
        return float(np.mean(f0_voiced)), float(np.std(f0_voiced))
    except Exception as exc:
        logger.debug("parselmouth pitch failed: %s", exc)
        return None, None


def _pitch_stats_librosa(
    y: np.ndarray, sr: int
) -> tuple[float | None, float | None]:
    """Fallback pitch extraction via librosa pyin."""
    try:
        f0, voiced, _ = librosa.pyin(
            y, fmin=_PITCH_FMIN, fmax=_PITCH_FMAX, sr=sr, hop_length=_HOP_LENGTH
        )
        if f0 is None:
            return None, None
        f0_valid = f0[~np.isnan(f0)]
        if f0_valid.size == 0:
            return None, None
        return float(np.mean(f0_valid)), float(np.std(f0_valid))
    except Exception as exc:
        logger.debug("librosa pyin failed: %s", exc)
        return None, None


def _pitch_stats(y: np.ndarray, sr: int) -> tuple[float | None, float | None]:
    """Best-effort pitch mean & std (parselmouth → librosa fallback)."""
    mean, std = _pitch_stats_parselmouth(y, sr)
    if mean is not None:
        return mean, std
    return _pitch_stats_librosa(y, sr)


def _energy_stats(y: np.ndarray, sr: int) -> tuple[float | None, float | None]:
    """RMS energy in dB — mean and std."""
    if y.size == 0:
        return None, None
    rms = librosa.feature.rms(y=y, hop_length=_HOP_LENGTH)[0]
    if rms.size == 0:
        return None, None
    # Avoid log(0) — floor at a small value
    rms = np.maximum(rms, 1e-10)
    db = librosa.amplitude_to_db(rms, ref=np.max)
    return float(np.mean(db)), float(np.std(db))


def _speech_rate_from_transcript(text: str, duration_s: float) -> float | None:
    """Words-per-minute from transcript text and known duration."""
    if not text or duration_s <= 0:
        return None
    words = re.findall(r"[A-Za-z\u0900-\u097F']+", text)  # English + Devanagari
    if not words:
        return None
    return (len(words) / duration_s) * 60.0


def _speech_rate_from_onsets(y: np.ndarray, sr: int, duration_s: float) -> float | None:
    """Estimate speech rate from onset detection (syllable proxy)."""
    if duration_s <= 0 or y.size == 0:
        return None
    try:
        onsets = librosa.onset.onset_detect(y=y, sr=sr, units="time")
        if len(onsets) == 0:
            return None
        syllables = len(onsets)
        words_est = syllables / 1.5
        return (words_est / duration_s) * 60.0
    except Exception:
        return None


def _detect_filler_words(text: str) -> list[tuple[str, int]]:
    """Find filler words in transcript text. Returns (pattern, count) pairs."""
    if not text:
        return []
    lower = text.lower()
    results = []
    for pattern in _FILLER_PATTERNS:
        matches = re.findall(rf"\b{re.escape(pattern)}\b", lower)
        if matches:
            results.append((pattern, len(matches)))
    return results


def _confidence_score(
    pause_ratio: float,
    pitch_cv: float | None,
    energy_cv: float | None,
) -> float:
    """Compute a vocal confidence proxy ∈ [0, 1].

    Higher = more confident-sounding speech (fewer pauses, stable pitch/energy).
    """
    score = 0.0
    weights_sum = 0.0

    # Pause component — fewer pauses → higher confidence
    w_pause = 0.4
    score += w_pause * (1.0 - min(1.0, pause_ratio * 2))  # scale: 50% pause = 0
    weights_sum += w_pause

    # Pitch stability
    if pitch_cv is not None:
        w_pitch = 0.35
        score += w_pitch * (1.0 - min(1.0, pitch_cv))
        weights_sum += w_pitch

    # Energy stability
    if energy_cv is not None:
        w_energy = 0.25
        score += w_energy * (1.0 - min(1.0, energy_cv / 10.0))  # 10 dB std = 0
        weights_sum += w_energy

    if weights_sum > 0:
        score /= weights_sum
    return max(0.0, min(1.0, score))


# ---------------------------------------------------------------------------
# Turn-level extraction
# ---------------------------------------------------------------------------

@dataclass
class _TurnInfo:
    """Lightweight turn descriptor for slicing."""
    turn_index: int
    speaker: str
    start_ms: int
    end_ms: int
    text: str


def _slice_audio(
    y: np.ndarray, sr: int, start_ms: int, end_ms: int
) -> np.ndarray:
    """Return the audio segment between start_ms and end_ms."""
    s = int(start_ms * sr / 1000)
    e = int(end_ms * sr / 1000)
    s = max(0, min(s, len(y)))
    e = max(s, min(e, len(y)))
    return y[s:e]


def _extract_turn_features(
    y_turn: np.ndarray,
    sr: int,
    turn: _TurnInfo,
) -> tuple[TurnAudioFeatures, list[PauseEvent], list[DysfluencyEvent]]:
    """Extract all audio features for a single turn."""
    duration_s = len(y_turn) / sr if sr > 0 else 0.0

    # Pitch
    pitch_mean, pitch_std = _pitch_stats(y_turn, sr) if y_turn.size > sr * 0.3 else (None, None)

    # Energy
    energy_mean, energy_std = _energy_stats(y_turn, sr)

    # Speech rate: prefer transcript-based, fallback to onset
    wpm = _speech_rate_from_transcript(turn.text, duration_s)
    if wpm is None:
        wpm = _speech_rate_from_onsets(y_turn, sr, duration_s)

    # Pauses
    pauses = _detect_pauses_in_segment(y_turn, sr, offset_ms=turn.start_ms)
    for p in pauses:
        p.turn_index = turn.turn_index
    total_pause_ms = sum(p.duration_ms for p in pauses)

    # Filler-word dysfluencies (deterministic)
    fillers = _detect_filler_words(turn.text)
    dysfluencies: list[DysfluencyEvent] = []
    for pattern, count in fillers:
        for _ in range(count):
            dysfluencies.append(DysfluencyEvent(
                turn_index=turn.turn_index,
                dysfluency_type=DysfluencyType.filler,
                text=pattern,
                confidence=0.8,
            ))

    # Pause ratio for confidence calc
    pause_ratio = (total_pause_ms / 1000.0) / duration_s if duration_s > 0 else 0.0
    pitch_cv = (pitch_std / pitch_mean) if (pitch_mean and pitch_std and pitch_mean > 0) else None
    conf = _confidence_score(pause_ratio, pitch_cv, energy_std)

    features = TurnAudioFeatures(
        turn_index=turn.turn_index,
        start_ms=turn.start_ms,
        end_ms=turn.end_ms,
        speech_rate_wpm=round(wpm, 1) if wpm else None,
        pitch_mean_hz=round(pitch_mean, 2) if pitch_mean else None,
        pitch_std_hz=round(pitch_std, 2) if pitch_std else None,
        energy_mean_db=round(energy_mean, 2) if energy_mean is not None else None,
        energy_std_db=round(energy_std, 2) if energy_std is not None else None,
        pause_count=len(pauses),
        pause_total_ms=total_pause_ms,
        dysfluency_count=len(dysfluencies),
        confidence_score=round(conf, 3),
    )

    return features, pauses, dysfluencies


# ---------------------------------------------------------------------------
# Inter-turn pause detection
# ---------------------------------------------------------------------------

def _detect_inter_turn_pauses(turns: list[_TurnInfo]) -> list[PauseEvent]:
    """Detect silences *between* consecutive turns."""
    pauses: list[PauseEvent] = []
    for i in range(1, len(turns)):
        gap_ms = turns[i].start_ms - turns[i - 1].end_ms
        if gap_ms >= _MIN_PAUSE_MS:
            pauses.append(PauseEvent(
                start_ms=turns[i - 1].end_ms,
                end_ms=turns[i].start_ms,
                duration_ms=gap_ms,
                is_inter_turn=True,
            ))
    return pauses


# ---------------------------------------------------------------------------
# Window aggregation
# ---------------------------------------------------------------------------

@dataclass
class _WindowSpec:
    """Topic window definition for aggregation."""
    window_id: uuid.UUID | None
    topic_key: str
    start_ms: int
    end_ms: int
    turn_indices: list[int]


def _aggregate_window(
    spec: _WindowSpec,
    turn_features: dict[int, TurnAudioFeatures],
) -> WindowAudioSummary:
    """Aggregate per-turn features into a single window summary."""
    matched = [turn_features[i] for i in spec.turn_indices if i in turn_features]

    if not matched:
        return WindowAudioSummary(
            window_id=spec.window_id,
            topic_key=spec.topic_key,
            start_ms=spec.start_ms,
            end_ms=spec.end_ms,
        )

    rates = [t.speech_rate_wpm for t in matched if t.speech_rate_wpm is not None]
    pitches = [t.pitch_mean_hz for t in matched if t.pitch_mean_hz is not None]
    pitch_stds = [t.pitch_std_hz for t in matched if t.pitch_std_hz is not None]
    energy_stds = [t.energy_std_db for t in matched if t.energy_std_db is not None]
    confs = [t.confidence_score for t in matched if t.confidence_score is not None]
    total_pause = sum(t.pause_total_ms for t in matched)

    # Pitch variability = CoV of per-turn pitch means
    pitch_variability = None
    if len(pitches) >= 2:
        pm = np.mean(pitches)
        if pm > 0:
            pitch_variability = float(np.std(pitches) / pm)

    # Energy variability = mean of per-turn energy stds
    energy_variability = float(np.mean(energy_stds)) if energy_stds else None

    # Confidence volatility = std of per-turn confidence scores
    conf_vol = float(np.std(confs)) if len(confs) >= 2 else None

    return WindowAudioSummary(
        window_id=spec.window_id,
        topic_key=spec.topic_key,
        start_ms=spec.start_ms,
        end_ms=spec.end_ms,
        avg_speech_rate_wpm=round(float(np.mean(rates)), 1) if rates else None,
        avg_pitch_hz=round(float(np.mean(pitches)), 2) if pitches else None,
        pitch_variability=round(pitch_variability, 4) if pitch_variability is not None else None,
        energy_variability=round(energy_variability, 4) if energy_variability is not None else None,
        total_pause_ms=total_pause,
        confidence_volatility=round(conf_vol, 4) if conf_vol is not None else None,
    )


# ---------------------------------------------------------------------------
# Reliability scoring
# ---------------------------------------------------------------------------

def _compute_reliability(
    y: np.ndarray, sr: int, turn_features: list[TurnAudioFeatures]
) -> float:
    """Score audio quality/reliability ∈ [0, 1].

    Penalises: short duration, excessive silence, clipping, few voiced turns.
    """
    if y.size == 0 or sr == 0:
        return 0.0

    duration_s = len(y) / sr
    score = 1.0

    # Penalty for very short audio (<10s)
    if duration_s < 10:
        score *= max(0.2, duration_s / 10.0)

    # Silence ratio penalty
    nonsilent = librosa.effects.split(y, top_db=_TOP_DB_SILENCE)
    if nonsilent.size == 0:
        return 0.05  # Essentially all silence
    voiced_samples = sum(int(iv[1] - iv[0]) for iv in nonsilent)
    silence_ratio = 1.0 - (voiced_samples / len(y))
    if silence_ratio > 0.7:
        score *= 0.3
    elif silence_ratio > 0.5:
        score *= 0.6

    # Clipping penalty
    clip_ratio = np.mean(np.abs(y) > 0.99)
    if clip_ratio > 0.05:
        score *= 0.5

    # Penalty if very few turns had extractable pitch
    if turn_features:
        pitched = sum(1 for t in turn_features if t.pitch_mean_hz is not None)
        pitch_coverage = pitched / len(turn_features)
        if pitch_coverage < 0.3:
            score *= 0.7

    return max(0.0, min(1.0, round(score, 3)))


# ---------------------------------------------------------------------------
# Gemini-based dysfluency enrichment
# ---------------------------------------------------------------------------

async def _enrich_dysfluencies_gemini(
    turns: list[_TurnInfo],
    existing: list[DysfluencyEvent],
) -> list[DysfluencyEvent]:
    """Call Gemini to detect transcript-level dysfluencies beyond filler words.

    Only processes student turns with enough text. Gracefully degrades if
    Gemini is unavailable.
    """
    if not settings.gemini_api_key:
        logger.info("No Gemini API key — skipping LLM dysfluency enrichment")
        return existing

    # Filter to student turns with substantive text
    candidate_turns = [
        t for t in turns
        if t.speaker == "student" and len(t.text.split()) >= 4
    ]
    if not candidate_turns:
        return existing

    try:
        from google import genai

        client = genai.Client(api_key=settings.gemini_api_key)
        enriched = list(existing)

        # Batch turns into a single prompt to minimise API calls
        batch_text = "\n\n".join(
            f"[Turn {t.turn_index}]: {t.text}" for t in candidate_turns
        )
        prompt = (
            "You are a speech-language analysis system. Given transcript turns "
            "from a counselling session, identify speech dysfluencies in EACH turn.\n\n"
            "For each dysfluency found, return a JSON array of objects with:\n"
            '- "turn_index": integer\n'
            '- "type": one of "repetition", "false_start", "filler", "prolongation", "block"\n'
            '- "text": the dysfluent segment\n'
            '- "confidence": 0.0-1.0\n\n'
            "If no dysfluencies in a turn, omit it. Return ONLY the JSON array.\n\n"
            f"Transcript turns:\n{batch_text}"
        )

        response = client.models.generate_content(
            model=settings.gemini_synthesis_model,
            contents=prompt,
            config={
                "temperature": 0.1,
                "max_output_tokens": 2048,
            },
        )

        raw = response.text.strip()
        # Extract JSON from possible markdown fencing
        if "```" in raw:
            match = re.search(r"```(?:json)?\s*(.*?)```", raw, re.DOTALL)
            if match:
                raw = match.group(1).strip()

        items = json.loads(raw)
        if not isinstance(items, list):
            return enriched

        # Deduplicate against existing filler detections
        existing_keys = {
            (d.turn_index, d.text, d.dysfluency_type) for d in existing
        }

        for item in items:
            dtype_str = item.get("type", "filler")
            try:
                dtype = DysfluencyType(dtype_str)
            except ValueError:
                dtype = DysfluencyType.filler

            turn_idx = item.get("turn_index", 0)
            text = item.get("text", "")
            key = (turn_idx, text, dtype)
            if key in existing_keys:
                continue

            enriched.append(DysfluencyEvent(
                turn_index=turn_idx,
                dysfluency_type=dtype,
                text=text,
                confidence=min(1.0, max(0.0, float(item.get("confidence", 0.6)))),
            ))
            existing_keys.add(key)

        logger.info("Gemini dysfluency enrichment added %d events", len(enriched) - len(existing))
        return enriched

    except Exception as exc:
        logger.warning("Gemini dysfluency enrichment failed: %s", exc)
        return existing


# ---------------------------------------------------------------------------
# Main extractor
# ---------------------------------------------------------------------------

class AudioSignalExtractor:
    """Turn-aware audio feature extraction pipeline.

    Usage::

        extractor = AudioSignalExtractor()
        features = await extractor.extract(
            session_id=...,
            audio_path="artifacts/sessions/<id>/audio.wav",
            turns=[...],
            windows=[...],
        )
    """

    def __init__(self, *, use_gemini: bool = True) -> None:
        self.use_gemini = use_gemini

    async def extract(
        self,
        session_id: uuid.UUID,
        audio_path: str,
        turns: list[dict[str, Any]],
        windows: list[dict[str, Any]] | None = None,
    ) -> AudioFeatures:
        """Run the full extraction pipeline.

        Args:
            session_id: Session UUID.
            audio_path: Path to the session audio file (wav/webm/etc).
            turns: List of turn dicts with keys: turn_index, speaker,
                   start_ms, end_ms, text.
            windows: Optional list of topic window dicts with keys:
                     window_id, topic_key, start_ms, end_ms, turn_indices.

        Returns:
            AudioFeatures with per-turn, per-window, and session-level data.
        """
        # -- Load audio -------------------------------------------------------
        y, sr = load_audio(audio_path)
        if y is None or sr is None:
            logger.error("Cannot extract audio features — load failed for %s", audio_path)
            return AudioFeatures(
                session_id=session_id,
                reliability_score=0.0,
            )

        # -- Parse turns -------------------------------------------------------
        turn_infos = [
            _TurnInfo(
                turn_index=t["turn_index"],
                speaker=t.get("speaker", "student"),
                start_ms=t["start_ms"],
                end_ms=t["end_ms"],
                text=t.get("text", ""),
            )
            for t in turns
        ]
        # Sort by start time
        turn_infos.sort(key=lambda t: t.start_ms)

        # -- Per-turn extraction -----------------------------------------------
        all_turn_features: list[TurnAudioFeatures] = []
        all_pauses: list[PauseEvent] = []
        all_dysfluencies: list[DysfluencyEvent] = []

        for turn in turn_infos:
            y_turn = _slice_audio(y, sr, turn.start_ms, turn.end_ms)
            if y_turn.size == 0:
                # Empty segment — emit a skeleton
                all_turn_features.append(TurnAudioFeatures(
                    turn_index=turn.turn_index,
                    start_ms=turn.start_ms,
                    end_ms=turn.end_ms,
                ))
                continue

            tf, pauses, dysf = _extract_turn_features(y_turn, sr, turn)
            all_turn_features.append(tf)
            all_pauses.extend(pauses)
            all_dysfluencies.extend(dysf)

        # -- Inter-turn pauses -------------------------------------------------
        inter_pauses = _detect_inter_turn_pauses(turn_infos)
        all_pauses.extend(inter_pauses)
        all_pauses.sort(key=lambda p: p.start_ms)

        # -- Gemini dysfluency enrichment --------------------------------------
        if self.use_gemini:
            all_dysfluencies = await _enrich_dysfluencies_gemini(
                turn_infos, all_dysfluencies
            )

        # -- Window aggregation ------------------------------------------------
        turn_feat_map = {tf.turn_index: tf for tf in all_turn_features}
        window_summaries: list[WindowAudioSummary] = []

        if windows:
            for w in windows:
                spec = _WindowSpec(
                    window_id=w.get("window_id") or w.get("id"),
                    topic_key=w.get("topic_key", "unknown"),
                    start_ms=w["start_ms"],
                    end_ms=w["end_ms"],
                    turn_indices=w.get("turn_indices", w.get("source_turn_indices", [])),
                )
                window_summaries.append(_aggregate_window(spec, turn_feat_map))

        # -- Session-level aggregates ------------------------------------------
        rates = [t.speech_rate_wpm for t in all_turn_features if t.speech_rate_wpm]
        pitches = [t.pitch_mean_hz for t in all_turn_features if t.pitch_mean_hz]
        energies = [t.energy_mean_db for t in all_turn_features if t.energy_mean_db is not None]

        session_wpm = round(float(np.mean(rates)), 1) if rates else None
        session_pitch = round(float(np.mean(pitches)), 2) if pitches else None
        session_energy = round(float(np.mean(energies)), 2) if energies else None

        # -- Reliability -------------------------------------------------------
        reliability = _compute_reliability(y, sr, all_turn_features)

        return AudioFeatures(
            session_id=session_id,
            turn_features=all_turn_features,
            pauses=all_pauses,
            dysfluencies=all_dysfluencies,
            window_summaries=window_summaries,
            session_speech_rate_wpm=session_wpm,
            session_pitch_mean_hz=session_pitch,
            session_energy_mean_db=session_energy,
            reliability_score=reliability,
        )


# ---------------------------------------------------------------------------
# Convenience function for worker jobs
# ---------------------------------------------------------------------------

async def extract_audio_features(
    session_id: uuid.UUID,
    audio_path: str,
    turns: list[dict[str, Any]],
    windows: list[dict[str, Any]] | None = None,
    *,
    use_gemini: bool = True,
) -> AudioFeatures:
    """One-shot convenience wrapper around AudioSignalExtractor."""
    extractor = AudioSignalExtractor(use_gemini=use_gemini)
    return await extractor.extract(session_id, audio_path, turns, windows)
