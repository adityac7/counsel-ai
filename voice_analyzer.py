"""Voice prosody analysis using librosa and parselmouth."""
from __future__ import annotations

import math
import os
import re
from typing import Any, Dict, List, Optional

import librosa
import numpy as np

try:
    import parselmouth
    HAS_PARSELMOUTH = True
except ImportError:
    parselmouth = None
    HAS_PARSELMOUTH = False

def detect_pauses(audio_path: str, min_duration: float = 0.5) -> List[Dict[str, float]]:
    """Detect pauses in audio based on silence intervals."""
    print(f"[voice_analyzer] Detecting pauses in {audio_path}")
    if not os.path.exists(audio_path):
        print("[voice_analyzer] Error: audio file not found")
        return []

    try:
        y, sr = librosa.load(audio_path, sr=None)
    except Exception as exc:
        print(f"[voice_analyzer] Error: failed to load audio ({exc})")
        return []

    if y.size == 0:
        print("[voice_analyzer] Error: empty audio")
        return []

    duration = len(y) / sr
    nonsilent = librosa.effects.split(y, top_db=30)

    pauses: List[Dict[str, float]] = []
    last_end = 0.0
    if nonsilent.size == 0:
        if duration >= min_duration:
            pauses.append({"start": 0.0, "duration": duration})
        return pauses

    for interval in nonsilent:
        start = interval[0] / sr
        if start - last_end >= min_duration:
            pauses.append({"start": last_end, "duration": start - last_end})
        last_end = interval[1] / sr

    if duration - last_end >= min_duration:
        pauses.append({"start": last_end, "duration": duration - last_end})

    return pauses


def _estimate_speech_rate_from_onsets(y: np.ndarray, sr: int, duration: float) -> Dict[str, float]:
    onsets = librosa.onset.onset_detect(y=y, sr=sr, units="time")
    if len(onsets) == 0 or duration == 0:
        return {"words_per_minute": 0.0, "variation": 0.0}

    syllable_estimate = len(onsets)
    words_estimate = syllable_estimate / 1.5
    words_per_minute = (words_estimate / duration) * 60.0

    variation = 0.0
    if len(onsets) > 2:
        intervals = np.diff(onsets)
        mean_interval = np.mean(intervals) or 1.0
        variation = float(np.std(intervals) / mean_interval)

    return {"words_per_minute": float(words_per_minute), "variation": float(variation)}


def _filler_word_stats(transcript: Optional[str], duration: float) -> Dict[str, Any]:
    if not transcript:
        return {"count": 0, "per_minute": 0.0, "detected": []}

    transcript_lower = transcript.lower()
    patterns = ["um", "uh", "like", "you know", "er", "ah"]
    detected = []
    count = 0
    for pattern in patterns:
        matches = re.findall(rf"\\b{re.escape(pattern)}\\b", transcript_lower)
        if matches:
            detected.append(pattern)
            count += len(matches)

    per_minute = (count / duration) * 60.0 if duration > 0 else 0.0
    return {"count": count, "per_minute": float(per_minute), "detected": detected}


def _pitch_metrics(sound: parselmouth.Sound) -> Dict[str, Any]:
    pitch = sound.to_pitch()
    f0 = pitch.selected_array["frequency"]
    f0 = f0[f0 > 0]
    if f0.size == 0:
        return {"mean_hz": 0.0, "range_hz": [0.0, 0.0], "variation": 0.0, "spikes": []}

    mean_hz = float(np.mean(f0))
    min_hz = float(np.min(f0))
    max_hz = float(np.max(f0))
    std_hz = float(np.std(f0))
    variation = std_hz / mean_hz if mean_hz > 0 else 0.0

    spikes = []
    threshold = mean_hz + 2 * std_hz
    frame_count = pitch.get_number_of_frames()
    for i in range(frame_count):
        hz = pitch.get_value_in_frame(i + 1)
        if hz and hz > threshold:
            time = pitch.xs(i + 1)
            spikes.append({"timestamp": float(time), "hz": float(hz), "context": "emotional_moment"})

    return {
        "mean_hz": mean_hz,
        "range_hz": [min_hz, max_hz],
        "variation": float(variation),
        "spikes": spikes,
    }


def _volume_metrics(y: np.ndarray, sr: int) -> Dict[str, Any]:
    rms = librosa.feature.rms(y=y)[0]
    times = librosa.times_like(rms, sr=sr)
    db = librosa.amplitude_to_db(rms, ref=np.max)
    mean_db = float(np.mean(db))

    slope = 0.0
    if len(times) > 1:
        slope = np.polyfit(times, db, 1)[0]

    if slope < -0.5:
        pattern = "trailing_off"
    elif slope > 0.5:
        pattern = "increasing"
    elif float(np.std(db)) > 6.0:
        pattern = "fluctuating"
    else:
        pattern = "steady"

    drops = []
    for i in range(1, len(db)):
        if db[i] < mean_db - 8.0 and db[i] < db[i - 1] - 4.0:
            drops.append({"timestamp": float(times[i]), "description": "volume_drop"})

    return {"mean_db": mean_db, "pattern": pattern, "drops": drops}


def _voice_quality(sound: parselmouth.Sound) -> Dict[str, float]:
    try:
        point_process = parselmouth.praat.call(
            sound, "To PointProcess (periodic, cc)", 75, 500
        )
        jitter = parselmouth.praat.call(
            point_process, "Get jitter (local)", 0, 0, 0.0001, 0.02, 1.3
        )
        shimmer = parselmouth.praat.call(
            [sound, point_process], "Get shimmer (local)", 0, 0, 0.0001, 0.02, 1.3, 1.6
        )
        harmonicity = parselmouth.praat.call(
            sound, "To Harmonicity (cc)", 0.01, 75, 0.1, 1.0
        )
        hnr = parselmouth.praat.call(harmonicity, "Get mean", 0, 0)
    except Exception:
        jitter = 0.0
        shimmer = 0.0
        hnr = 20.0

    tremor_score = float(min(1.0, jitter * 10.0 + shimmer * 2.0))
    breathiness = float(min(1.0, max(0.0, (20.0 - hnr) / 20.0)))
    steadiness_score = float(max(0.0, 1.0 - tremor_score))

    return {
        "tremor_score": tremor_score,
        "breathiness": breathiness,
        "steadiness_score": steadiness_score,
    }


def analyze_audio(audio_path: str, transcript: Optional[str] = None) -> Dict[str, Any]:
    """Analyze voice prosody from an audio file."""
    print(f"[voice_analyzer] Starting analysis for {audio_path}")
    if not os.path.exists(audio_path):
        print("[voice_analyzer] Error: audio file not found")
        return {}

    try:
        y, sr = librosa.load(audio_path, sr=None)
    except Exception as exc:
        print(f"[voice_analyzer] Error: corrupted audio ({exc})")
        return {}

    if y.size == 0:
        print("[voice_analyzer] Error: empty audio")
        return {}

    duration = len(y) / sr
    if duration < 0.5:
        print("[voice_analyzer] Error: audio too short")
        return {}

    pauses = detect_pauses(audio_path)
    total_pause = sum(pause["duration"] for pause in pauses)
    pause_ratio = total_pause / duration if duration > 0 else 0.0

    if transcript:
        words = re.findall(r"[A-Za-z']+", transcript)
        words_per_minute = (len(words) / duration) * 60.0
        speech_variation = 0.0
    else:
        speech_rate = _estimate_speech_rate_from_onsets(y, sr, duration)
        words_per_minute = speech_rate["words_per_minute"]
        speech_variation = speech_rate["variation"]

    speech_rate_metrics = {
        "words_per_minute": float(words_per_minute),
        "variation": float(speech_variation),
    }

    filler_words = _filler_word_stats(transcript, duration)

    try:
        sound = parselmouth.Sound(audio_path) if HAS_PARSELMOUTH else None
        pitch_metrics = _pitch_metrics(sound)
        voice_quality = _voice_quality(sound)
    except Exception as exc:
        print(f"[voice_analyzer] Warning: parselmouth failure ({exc})")
        pitch_metrics = {"mean_hz": 0.0, "range_hz": [0.0, 0.0], "variation": 0.0, "spikes": []}
        voice_quality = {"tremor_score": 0.0, "breathiness": 0.0, "steadiness_score": 0.0}

    volume_metrics = _volume_metrics(y, sr)

    overall_confidence_score = (
        0.4 * (1.0 - min(1.0, pause_ratio))
        + 0.3 * (1.0 - min(1.0, speech_rate_metrics["variation"]))
        + 0.2 * (1.0 - min(1.0, pitch_metrics["variation"]))
        + 0.1 * voice_quality["steadiness_score"]
    )
    overall_confidence_score = float(max(0.0, min(1.0, overall_confidence_score)))

    result = {
        "speech_rate": speech_rate_metrics,
        "pauses": {
            "count": len(pauses),
            "total_duration": float(total_pause),
            "avg_duration": float(total_pause / len(pauses)) if pauses else 0.0,
            "long_pauses": [
                {**pause, "type": "hesitation"}
                for pause in pauses
                if pause["duration"] > 2.0
            ],
            "pause_ratio": float(pause_ratio),
        },
        "pitch": pitch_metrics,
        "volume": volume_metrics,
        "filler_words": filler_words,
        "voice_quality": voice_quality,
        "overall_confidence_score": overall_confidence_score,
    }

    print("[voice_analyzer] Analysis complete")
    return result
