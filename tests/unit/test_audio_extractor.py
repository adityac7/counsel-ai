"""Tests for counselai.signals.audio.extractor.

Covers:
  - Audio loading (good file, missing file, empty file)
  - Per-turn feature extraction
  - Pause detection
  - Filler-word dysfluency detection
  - Inter-turn pause detection
  - Window aggregation
  - Reliability scoring
  - Full pipeline (extract) with synthetic audio
  - Graceful degradation with bad audio
"""

from __future__ import annotations

import json
import os
import struct
import tempfile
import uuid
import wave
from pathlib import Path

import asyncio
import numpy as np
import pytest

# Ensure src/ is importable
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

# Helper to run async in sync tests
def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()

from counselai.signals.audio.extractor import (
    AudioSignalExtractor,
    _confidence_score,
    _detect_filler_words,
    _detect_inter_turn_pauses,
    _detect_pauses_in_segment,
    _energy_stats,
    _pitch_stats_librosa,
    _slice_audio,
    _TurnInfo,
    load_audio,
)
from counselai.signals.audio.schemas import (
    AudioFeatures,
    DysfluencyType,
    TurnAudioFeatures,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_wav(path: str, duration_s: float = 3.0, sr: int = 16000, freq: float = 220.0):
    """Generate a simple sine-wave WAV file."""
    n_samples = int(sr * duration_s)
    t = np.linspace(0, duration_s, n_samples, endpoint=False)
    audio = (0.5 * np.sin(2 * np.pi * freq * t) * 32767).astype(np.int16)
    with wave.open(path, "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(audio.tobytes())


def _make_silent_wav(path: str, duration_s: float = 2.0, sr: int = 16000):
    """Generate a silent WAV file."""
    n_samples = int(sr * duration_s)
    audio = np.zeros(n_samples, dtype=np.int16)
    with wave.open(path, "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(audio.tobytes())


def _make_speech_like_wav(path: str, sr: int = 16000):
    """Generate a WAV with alternating speech (sine) and silence segments.

    Pattern: 1s speech | 0.6s silence | 1.5s speech | 0.8s silence | 1s speech
    Total ≈ 4.9s
    """
    segments = [
        ("speech", 1.0, 200.0),
        ("silence", 0.6, 0.0),
        ("speech", 1.5, 250.0),
        ("silence", 0.8, 0.0),
        ("speech", 1.0, 180.0),
    ]
    samples = []
    for kind, dur, freq in segments:
        n = int(sr * dur)
        t = np.linspace(0, dur, n, endpoint=False)
        if kind == "speech":
            seg = (0.5 * np.sin(2 * np.pi * freq * t) * 32767).astype(np.int16)
        else:
            seg = np.zeros(n, dtype=np.int16)
        samples.append(seg)
    audio = np.concatenate(samples)
    with wave.open(path, "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(audio.tobytes())


@pytest.fixture
def tmp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield d


@pytest.fixture
def sine_wav(tmp_dir):
    p = os.path.join(tmp_dir, "sine.wav")
    _make_wav(p)
    return p


@pytest.fixture
def silent_wav(tmp_dir):
    p = os.path.join(tmp_dir, "silent.wav")
    _make_silent_wav(p)
    return p


@pytest.fixture
def speech_wav(tmp_dir):
    p = os.path.join(tmp_dir, "speech.wav")
    _make_speech_like_wav(p)
    return p


# ---------------------------------------------------------------------------
# Audio loading tests
# ---------------------------------------------------------------------------

class TestLoadAudio:
    def test_load_valid_wav(self, sine_wav):
        y, sr = load_audio(sine_wav)
        assert y is not None
        assert sr is not None
        assert y.size > 0

    def test_load_missing_file(self):
        y, sr = load_audio("/nonexistent/file.wav")
        assert y is None
        assert sr is None

    def test_load_empty_file(self, tmp_dir):
        p = os.path.join(tmp_dir, "empty.wav")
        Path(p).write_bytes(b"")
        y, sr = load_audio(p)
        assert y is None
        assert sr is None


# ---------------------------------------------------------------------------
# Pause detection tests
# ---------------------------------------------------------------------------

class TestPauseDetection:
    def test_pauses_in_speech_like_audio(self, speech_wav):
        y, sr = load_audio(speech_wav)
        pauses = _detect_pauses_in_segment(y, sr, offset_ms=0)
        # Should detect at least 1 pause (the 0.6s and 0.8s silences)
        assert len(pauses) >= 1
        for p in pauses:
            assert p.duration_ms >= 400  # _MIN_PAUSE_MS

    def test_no_pauses_in_continuous_tone(self, sine_wav):
        y, sr = load_audio(sine_wav)
        pauses = _detect_pauses_in_segment(y, sr, offset_ms=0)
        assert len(pauses) == 0

    def test_all_silence_is_one_pause(self):
        """Pure digital silence (zeros) triggers the nonsilent.size==0 path."""
        sr = 16000
        y = np.zeros(sr * 2, dtype=np.float32)  # 2s of silence
        pauses = _detect_pauses_in_segment(y, sr, offset_ms=0)
        # librosa.effects.split returns empty for all-zero → our code creates one big pause
        assert len(pauses) >= 1
        assert pauses[0].duration_ms >= 1500

    def test_offset_applied(self, speech_wav):
        y, sr = load_audio(speech_wav)
        pauses = _detect_pauses_in_segment(y, sr, offset_ms=5000)
        for p in pauses:
            assert p.start_ms >= 5000


# ---------------------------------------------------------------------------
# Inter-turn pause detection
# ---------------------------------------------------------------------------

class TestInterTurnPauses:
    def test_detects_gap_between_turns(self):
        turns = [
            _TurnInfo(0, "student", 0, 2000, "hello"),
            _TurnInfo(1, "counsellor", 3000, 5000, "hi"),
        ]
        pauses = _detect_inter_turn_pauses(turns)
        assert len(pauses) == 1
        assert pauses[0].is_inter_turn is True
        assert pauses[0].duration_ms == 1000

    def test_no_gap(self):
        turns = [
            _TurnInfo(0, "student", 0, 2000, "hello"),
            _TurnInfo(1, "counsellor", 2000, 4000, "hi"),
        ]
        pauses = _detect_inter_turn_pauses(turns)
        assert len(pauses) == 0

    def test_small_gap_below_threshold(self):
        turns = [
            _TurnInfo(0, "student", 0, 2000, "hello"),
            _TurnInfo(1, "counsellor", 2200, 4000, "hi"),
        ]
        pauses = _detect_inter_turn_pauses(turns)
        assert len(pauses) == 0  # 200ms < 400ms threshold


# ---------------------------------------------------------------------------
# Filler word detection
# ---------------------------------------------------------------------------

class TestFillerWords:
    def test_basic_fillers(self):
        text = "Um I think like you know it's um basically fine"
        fillers = _detect_filler_words(text)
        patterns = {f[0] for f in fillers}
        assert "um" in patterns
        assert "like" in patterns
        assert "you know" in patterns
        assert "basically" in patterns

    def test_no_fillers(self):
        text = "I want to become a doctor"
        fillers = _detect_filler_words(text)
        assert len(fillers) == 0

    def test_empty_text(self):
        assert _detect_filler_words("") == []
        assert _detect_filler_words(None) == []


# ---------------------------------------------------------------------------
# Confidence score
# ---------------------------------------------------------------------------

class TestConfidenceScore:
    def test_perfect_confidence(self):
        score = _confidence_score(0.0, 0.0, 0.0)
        assert score > 0.9

    def test_low_confidence_many_pauses(self):
        score = _confidence_score(0.8, 0.5, 5.0)
        assert score < 0.5

    def test_bounds(self):
        for pr in [0.0, 0.5, 1.0]:
            for pcv in [None, 0.0, 0.5, 1.5]:
                for ecv in [None, 0.0, 5.0, 15.0]:
                    s = _confidence_score(pr, pcv, ecv)
                    assert 0.0 <= s <= 1.0


# ---------------------------------------------------------------------------
# Energy stats
# ---------------------------------------------------------------------------

class TestEnergyStats:
    def test_sine_wave_energy(self, sine_wav):
        y, sr = load_audio(sine_wav)
        mean_db, std_db = _energy_stats(y, sr)
        assert mean_db is not None
        assert std_db is not None
        # Steady sine should have low std
        assert std_db < 5.0

    def test_empty_array(self):
        mean_db, std_db = _energy_stats(np.array([], dtype=np.float32), 16000)
        assert mean_db is None
        assert std_db is None


# ---------------------------------------------------------------------------
# Slice audio
# ---------------------------------------------------------------------------

class TestSliceAudio:
    def test_basic_slice(self, sine_wav):
        y, sr = load_audio(sine_wav)
        sliced = _slice_audio(y, sr, 0, 1000)
        expected_len = int(1.0 * sr)
        assert abs(len(sliced) - expected_len) < sr * 0.01  # within 1%

    def test_out_of_bounds(self, sine_wav):
        y, sr = load_audio(sine_wav)
        sliced = _slice_audio(y, sr, 0, 999999)
        assert len(sliced) == len(y)


# ---------------------------------------------------------------------------
# Full pipeline tests
# ---------------------------------------------------------------------------

class TestAudioSignalExtractor:
    def test_extract_with_turns(self, speech_wav):
        session_id = uuid.uuid4()
        turns = [
            {"turn_index": 0, "speaker": "student", "start_ms": 0, "end_ms": 1000, "text": "Um hello"},
            {"turn_index": 1, "speaker": "counsellor", "start_ms": 1600, "end_ms": 3100, "text": "Tell me more"},
            {"turn_index": 2, "speaker": "student", "start_ms": 3900, "end_ms": 4900, "text": "I like think it's fine"},
        ]

        extractor = AudioSignalExtractor(use_gemini=False)
        result = _run(extractor.extract(
            session_id=session_id,
            audio_path=speech_wav,
            turns=turns,
        ))

        assert isinstance(result, AudioFeatures)
        assert result.session_id == session_id
        assert len(result.turn_features) == 3
        assert result.reliability_score > 0
        # Should detect filler in turn 0 ("um") or turn 2 ("like")
        filler_turns = {d.turn_index for d in result.dysfluencies if d.dysfluency_type == DysfluencyType.filler}
        assert 0 in filler_turns or 2 in filler_turns

    def test_extract_missing_audio(self):
        session_id = uuid.uuid4()
        extractor = AudioSignalExtractor(use_gemini=False)
        result = _run(extractor.extract(
            session_id=session_id,
            audio_path="/nonexistent/audio.wav",
            turns=[],
        ))
        assert result.reliability_score == 0.0
        assert len(result.turn_features) == 0

    def test_extract_no_turns(self, sine_wav):
        """Session-level features still emitted even without turns."""
        session_id = uuid.uuid4()
        extractor = AudioSignalExtractor(use_gemini=False)
        result = _run(extractor.extract(
            session_id=session_id,
            audio_path=sine_wav,
            turns=[],
        ))
        assert result.reliability_score > 0
        assert len(result.turn_features) == 0

    def test_extract_with_windows(self, speech_wav):
        session_id = uuid.uuid4()
        turns = [
            {"turn_index": 0, "speaker": "student", "start_ms": 0, "end_ms": 1000, "text": "hello"},
            {"turn_index": 1, "speaker": "student", "start_ms": 1600, "end_ms": 3100, "text": "more talk"},
            {"turn_index": 2, "speaker": "student", "start_ms": 3900, "end_ms": 4900, "text": "goodbye"},
        ]
        windows = [
            {
                "window_id": str(uuid.uuid4()),
                "topic_key": "greeting",
                "start_ms": 0,
                "end_ms": 1000,
                "turn_indices": [0],
            },
            {
                "window_id": str(uuid.uuid4()),
                "topic_key": "discussion",
                "start_ms": 1600,
                "end_ms": 4900,
                "turn_indices": [1, 2],
            },
        ]

        extractor = AudioSignalExtractor(use_gemini=False)
        result = _run(extractor.extract(
            session_id=session_id,
            audio_path=speech_wav,
            turns=turns,
            windows=windows,
        ))

        assert len(result.window_summaries) == 2
        assert result.window_summaries[0].topic_key == "greeting"
        assert result.window_summaries[1].topic_key == "discussion"

    def test_serialization_roundtrip(self, speech_wav):
        """AudioFeatures can serialize to JSON and back."""
        session_id = uuid.uuid4()
        turns = [
            {"turn_index": 0, "speaker": "student", "start_ms": 0, "end_ms": 2000, "text": "test"},
        ]
        extractor = AudioSignalExtractor(use_gemini=False)
        result = _run(extractor.extract(
            session_id=session_id,
            audio_path=speech_wav,
            turns=turns,
        ))

        # Serialize → deserialize
        json_str = result.model_dump_json()
        restored = AudioFeatures.model_validate_json(json_str)
        assert restored.session_id == session_id
        assert len(restored.turn_features) == len(result.turn_features)
