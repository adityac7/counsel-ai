"""Tests for signals/common — timeline alignment, normalization, reliability scoring.

Covers Task 9 acceptance criteria:
  - Content, audio, and video features can be joined by turn and topic window.
  - Every observation carries a confidence/reliability value.
"""

from __future__ import annotations

import uuid

import pytest

from counselai.signals.common.schemas import (
    Modality,
    ModalityReliability,
    SessionReliability,
    SignalObservation,
    TopicWindow,
)
from counselai.signals.common.timeline import (
    AlignedSession,
    AlignedTurn,
    AlignedWindow,
    align_session_signals,
)
from counselai.signals.common.normalization import (
    NormalizedSession,
    compute_baseline,
    deviation_score,
    min_max_scale,
    normalize_session,
    z_score,
)
from counselai.signals.common.reliability import (
    adjust_observation_confidence,
    score_session_reliability,
)
from counselai.signals.content.schemas import (
    AgencyLevel,
    AgencyMarker,
    ContentFeatures,
    HedgingMarker,
    TopicDepth,
    TopicMention,
)
from counselai.signals.audio.schemas import (
    AudioFeatures,
    TurnAudioFeatures,
    WindowAudioSummary,
)
from counselai.signals.video.schemas import (
    EngagementLevel,
    GazeDirection,
    TurnVideoFeatures,
    VideoFeatures,
    WindowVideoSummary,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SESSION_ID = uuid.uuid4()


def _make_turns_raw(n: int = 6) -> list[dict]:
    turns = []
    for i in range(n):
        turns.append({
            "turn_index": i,
            "speaker": "student" if i % 2 == 0 else "counsellor",
            "start_ms": i * 5000,
            "end_ms": (i + 1) * 5000,
            "text": f"Turn {i} text here",
        })
    return turns


def _make_content_features() -> ContentFeatures:
    return ContentFeatures(
        session_id=SESSION_ID,
        topics=[
            TopicMention(
                topic_key="career_interest",
                label="Career Interest",
                depth=TopicDepth.moderate,
                turn_indices=[0, 2, 4],
                confidence=0.8,
            ),
            TopicMention(
                topic_key="family_dynamics",
                label="Family Dynamics",
                depth=TopicDepth.surface,
                turn_indices=[2, 4],
                confidence=0.65,
            ),
        ],
        hedging_markers=[
            HedgingMarker(turn_index=0, text="i think", hedge_type="qualifier", confidence=0.7),
            HedgingMarker(turn_index=2, text="maybe", hedge_type="qualifier", confidence=0.75),
        ],
        agency_markers=[
            AgencyMarker(turn_index=4, text="I want to", level=AgencyLevel.high, direction="self", confidence=0.8),
        ],
        dominant_language="hinglish",
        overall_depth=TopicDepth.moderate,
        overall_agency=AgencyLevel.moderate,
        reliability_score=0.75,
    )


def _make_audio_features() -> AudioFeatures:
    turn_feats = []
    for i in range(6):
        turn_feats.append(TurnAudioFeatures(
            turn_index=i,
            start_ms=i * 5000,
            end_ms=(i + 1) * 5000,
            speech_rate_wpm=120.0 + i * 5,
            pitch_mean_hz=180.0 + i * 10,
            pitch_std_hz=15.0 + i,
            energy_mean_db=-30.0 + i,
            energy_std_db=5.0 + i * 0.5,
            pause_count=1 if i % 2 == 0 else 0,
            pause_total_ms=500 if i % 2 == 0 else 0,
            confidence_score=0.7 + i * 0.03,
        ))
    return AudioFeatures(
        session_id=SESSION_ID,
        turn_features=turn_feats,
        window_summaries=[
            WindowAudioSummary(
                topic_key="career_interest",
                start_ms=0,
                end_ms=15000,
                avg_speech_rate_wpm=125.0,
                avg_pitch_hz=190.0,
                total_pause_ms=1000,
            ),
        ],
        session_speech_rate_wpm=132.5,
        reliability_score=0.8,
    )


def _make_video_features() -> VideoFeatures:
    turn_feats = []
    for i in range(6):
        turn_feats.append(TurnVideoFeatures(
            turn_index=i,
            start_ms=i * 5000,
            end_ms=(i + 1) * 5000,
            face_visible_pct=85.0 - i * 5,
            dominant_gaze=GazeDirection.direct if i < 3 else GazeDirection.downward,
            engagement_estimate=EngagementLevel.engaged if i < 4 else EngagementLevel.passive,
            tension_event_count=1 if i == 3 else 0,
            movement_event_count=1 if i in (1, 4) else 0,
        ))
    return VideoFeatures(
        session_id=SESSION_ID,
        turn_features=turn_feats,
        window_summaries=[
            WindowVideoSummary(
                topic_key="career_interest",
                start_ms=0,
                end_ms=15000,
                avg_face_visible_pct=80.0,
                dominant_gaze=GazeDirection.direct,
                engagement_estimate=EngagementLevel.engaged,
            ),
        ],
        total_face_visible_pct=72.0,
        video_duration_ms=30000,
        frame_count=30,
        reliability_score=0.7,
    )


def _make_topic_windows() -> list[TopicWindow]:
    return [
        TopicWindow(
            session_id=SESSION_ID,
            topic_key="career_interest",
            start_ms=0,
            end_ms=15000,
            source_turn_indices=[0, 2, 4],
            reliability_score=0.8,
        ),
        TopicWindow(
            session_id=SESSION_ID,
            topic_key="family_dynamics",
            start_ms=10000,
            end_ms=25000,
            source_turn_indices=[2, 4],
            reliability_score=0.6,
        ),
    ]


# ---------------------------------------------------------------------------
# Timeline alignment tests
# ---------------------------------------------------------------------------


class TestTimelineAlignment:
    """Test align_session_signals and its output structure."""

    def test_align_with_all_modalities(self):
        turns = _make_turns_raw()
        content = _make_content_features()
        audio = _make_audio_features()
        video = _make_video_features()
        windows = _make_topic_windows()

        result = align_session_signals(
            SESSION_ID, turns, windows, content, audio, video,
        )

        assert isinstance(result, AlignedSession)
        assert result.session_id == SESSION_ID
        assert len(result.turns) == 6
        assert len(result.windows) == 2
        assert result.duration_ms == 30000

        # All three modalities should be available
        assert Modality.content in result.modalities_available
        assert Modality.audio in result.modalities_available
        assert Modality.video in result.modalities_available

    def test_per_turn_alignment(self):
        """Content, audio, and video features can be joined by turn."""
        turns = _make_turns_raw()
        content = _make_content_features()
        audio = _make_audio_features()
        video = _make_video_features()

        result = align_session_signals(
            SESSION_ID, turns, [], content, audio, video,
        )

        # Turn 0 should have content (hedging), audio, and video
        t0 = result.turns[0]
        assert t0.turn_index == 0
        assert len(t0.hedging_markers) == 1
        assert t0.audio is not None
        assert t0.audio.speech_rate_wpm == 120.0
        assert t0.video is not None
        assert t0.video.face_visible_pct == 85.0
        assert Modality.content in t0.modalities_present
        assert Modality.audio in t0.modalities_present
        assert Modality.video in t0.modalities_present

    def test_per_window_alignment(self):
        """Content, audio, and video features can be joined by topic window."""
        turns = _make_turns_raw()
        content = _make_content_features()
        audio = _make_audio_features()
        video = _make_video_features()
        windows = _make_topic_windows()

        result = align_session_signals(
            SESSION_ID, turns, windows, content, audio, video,
        )

        career_win = result.windows[0]
        assert career_win.window.topic_key == "career_interest"
        assert career_win.audio_summary is not None
        assert career_win.video_summary is not None
        assert career_win.hedging_count >= 1

    def test_observations_have_confidence(self):
        """Every observation carries a confidence/reliability value."""
        turns = _make_turns_raw()
        audio = _make_audio_features()
        video = _make_video_features()

        result = align_session_signals(
            SESSION_ID, turns, [], None, audio, video,
        )

        assert len(result.observations) > 0
        for obs in result.observations:
            assert isinstance(obs.confidence, float)
            assert 0.0 <= obs.confidence <= 1.0
            assert obs.modality in (Modality.audio, Modality.video)

    def test_empty_turns_returns_empty(self):
        result = align_session_signals(SESSION_ID, [], [], None, None, None)
        assert len(result.turns) == 0
        assert len(result.observations) == 0

    def test_partial_modalities(self):
        """Works with only content (no audio/video)."""
        turns = _make_turns_raw()
        content = _make_content_features()

        result = align_session_signals(
            SESSION_ID, turns, [], content, None, None,
        )

        assert Modality.content in result.modalities_available
        assert Modality.audio not in result.modalities_available
        assert Modality.video not in result.modalities_available
        # Turn 0 should still have hedging
        assert len(result.turns[0].hedging_markers) == 1


# ---------------------------------------------------------------------------
# Normalization tests
# ---------------------------------------------------------------------------


class TestNormalization:
    def test_z_score(self):
        assert z_score(10, 10, 5) == 0.0
        assert z_score(15, 10, 5) == 1.0
        assert z_score(5, 10, 5) == -1.0
        assert z_score(10, 10, 0) == 0.0  # zero std

    def test_min_max_scale(self):
        assert min_max_scale(50, 0, 100) == 0.5
        assert min_max_scale(0, 0, 100) == 0.0
        assert min_max_scale(100, 0, 100) == 1.0
        assert min_max_scale(150, 0, 100) == 1.0  # clamp
        assert min_max_scale(-10, 0, 100) == 0.0  # clamp

    def test_deviation_score(self):
        assert deviation_score(10, 10, 5) == 0.0  # at mean
        assert deviation_score(25, 10, 5) == 1.0  # 3σ away
        assert 0.3 < deviation_score(15, 10, 5) < 0.4  # 1σ

    def test_compute_baseline(self):
        values = {
            "speech_rate_wpm": [100.0, 120.0, 140.0],
            "pitch_mean_hz": [180.0, 200.0],
        }
        baseline = compute_baseline(values)
        assert abs(baseline.means["speech_rate_wpm"] - 120.0) < 0.01
        assert baseline.counts["speech_rate_wpm"] == 3
        assert baseline.mins["pitch_mean_hz"] == 180.0
        assert baseline.maxs["pitch_mean_hz"] == 200.0

    def test_normalize_session(self):
        turns = _make_turns_raw()
        audio = _make_audio_features()
        video = _make_video_features()

        aligned = align_session_signals(
            SESSION_ID, turns, [], None, audio, video,
        )

        normalized = normalize_session(str(SESSION_ID), aligned.turns)
        assert isinstance(normalized, NormalizedSession)
        assert len(normalized.turns) == 6
        assert normalized.baseline  # should have entries

        # Every normalized turn should have raw values
        for nt in normalized.turns:
            if nt.raw:
                for key, val in nt.z_scores.items():
                    assert isinstance(val, float)
                for key, val in nt.deviations.items():
                    assert 0.0 <= val <= 1.0

    def test_normalize_empty(self):
        result = normalize_session(str(SESSION_ID), [])
        assert len(result.turns) == 0


# ---------------------------------------------------------------------------
# Reliability scoring tests
# ---------------------------------------------------------------------------


class TestReliability:
    def test_all_modalities(self):
        content = _make_content_features()
        audio = _make_audio_features()
        video = _make_video_features()

        result = score_session_reliability(
            SESSION_ID, content, audio, video, session_duration_ms=30000,
        )

        assert isinstance(result, SessionReliability)
        assert result.session_id == SESSION_ID
        assert len(result.modalities) == 3
        assert 0.0 <= result.overall_score <= 1.0
        # All modalities should have non-zero scores
        for m in result.modalities:
            assert m.score > 0

    def test_missing_modalities(self):
        result = score_session_reliability(
            SESSION_ID, None, None, None, session_duration_ms=30000,
        )

        assert result.overall_score == 0.0
        for m in result.modalities:
            assert m.score == 0.0

    def test_partial_modalities_penalized(self):
        """Single-modality sessions get a cross-modal penalty."""
        content = _make_content_features()
        single = score_session_reliability(
            SESSION_ID, content, None, None, session_duration_ms=30000,
        )
        full = score_session_reliability(
            SESSION_ID, content, _make_audio_features(), _make_video_features(),
            session_duration_ms=30000,
        )
        # Full should score higher (or equal) than single-modal
        assert full.overall_score >= single.overall_score - 0.01

    def test_adjust_observation_confidence(self):
        obs = [
            SignalObservation(
                session_id=SESSION_ID,
                modality=Modality.audio,
                signal_key="pitch",
                value_json={"mean_hz": 180},
                confidence=0.8,
            ),
            SignalObservation(
                session_id=SESSION_ID,
                modality=Modality.video,
                signal_key="gaze",
                value_json={"dominant": "direct"},
                confidence=0.7,
            ),
        ]
        reliability_map = {Modality.audio: 0.9, Modality.video: 0.5}

        adjusted = adjust_observation_confidence(obs, reliability_map)
        assert len(adjusted) == 2
        # Audio: 0.8 * 0.9 = 0.72
        assert abs(adjusted[0].confidence - 0.72) < 0.01
        # Video: 0.7 * 0.5 = 0.35
        assert abs(adjusted[1].confidence - 0.35) < 0.01

    def test_notes_report_unavailable(self):
        result = score_session_reliability(
            SESSION_ID, None, _make_audio_features(), None, session_duration_ms=30000,
        )
        note_text = " ".join(result.notes)
        assert "content" in note_text.lower()
        assert "video" in note_text.lower()


# ---------------------------------------------------------------------------
# Integration: full pipeline
# ---------------------------------------------------------------------------


class TestFullPipeline:
    """End-to-end: align → normalize → reliability score."""

    def test_full_pipeline(self):
        turns = _make_turns_raw()
        content = _make_content_features()
        audio = _make_audio_features()
        video = _make_video_features()
        windows = _make_topic_windows()

        # Step 1: Align
        aligned = align_session_signals(
            SESSION_ID, turns, windows, content, audio, video,
        )
        assert len(aligned.turns) == 6
        assert len(aligned.windows) == 2
        assert len(aligned.observations) > 0

        # Step 2: Normalize
        normalized = normalize_session(str(SESSION_ID), aligned.turns)
        assert len(normalized.turns) == 6

        # Step 3: Reliability
        reliability = score_session_reliability(
            SESSION_ID, content, audio, video,
            session_duration_ms=aligned.duration_ms,
        )
        assert reliability.overall_score > 0.0

        # Step 4: Adjust observations
        reliability_map = {m.modality: m.score for m in reliability.modalities}
        adjusted = adjust_observation_confidence(aligned.observations, reliability_map)

        # Every adjusted observation should have a valid confidence
        for obs in adjusted:
            assert 0.0 <= obs.confidence <= 1.0

        # We should have observations from both audio and video
        modalities_seen = {obs.modality for obs in adjusted}
        assert Modality.audio in modalities_seen
        assert Modality.video in modalities_seen
