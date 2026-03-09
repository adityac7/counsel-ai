"""Contract tests for signal extraction schemas (content, audio, video, common).

Validates Pydantic models for all three modalities plus cross-modal schemas.
"""

from __future__ import annotations

import json
import uuid

import pytest

from counselai.signals.common.schemas import (
    Modality,
    ObservationSource,
    SignalObservation,
    TimeSpan,
    TopicWindow,
)
from counselai.signals.content.schemas import (
    AgencyLevel,
    AgencyMarker,
    AvoidanceEvent,
    CodeSwitchDirection,
    ContentFeatures,
    HedgingMarker,
    TopicDepth,
    TopicMention,
)
from counselai.signals.audio.schemas import (
    AudioFeatures,
    DysfluencyEvent,
    DysfluencyType,
    PauseEvent,
    TurnAudioFeatures,
)
from counselai.signals.video.schemas import (
    EngagementLevel,
    FacePresenceSegment,
    GazeDirection,
    MovementType,
)


# ---------------------------------------------------------------------------
# Common schemas
# ---------------------------------------------------------------------------

class TestTimeSpan:
    def test_duration(self):
        span = TimeSpan(start_ms=1000, end_ms=5000)
        assert span.duration_ms == 4000

    def test_zero_duration(self):
        span = TimeSpan(start_ms=1000, end_ms=1000)
        assert span.duration_ms == 0


class TestTopicWindow:
    def test_roundtrip(self):
        sid = uuid.uuid4()
        tw = TopicWindow(
            session_id=sid,
            topic_key="career_interest",
            start_ms=0,
            end_ms=15000,
            source_turn_indices=[0, 1, 2],
            reliability_score=0.85,
        )
        data = json.loads(tw.model_dump_json())
        restored = TopicWindow(**data)
        assert restored.topic_key == "career_interest"
        assert restored.reliability_score == 0.85
        assert len(restored.source_turn_indices) == 3

    def test_defaults(self):
        tw = TopicWindow(session_id=uuid.uuid4(), topic_key="test", start_ms=0, end_ms=100)
        assert tw.source_turn_ids == []
        assert tw.reliability_score == 0.0


class TestSignalObservation:
    def test_full_observation(self):
        obs = SignalObservation(
            session_id=uuid.uuid4(),
            modality=Modality.content,
            signal_key="hedging",
            value_json={"text": "I think maybe"},
            confidence=0.8,
        )
        assert obs.modality == Modality.content
        assert obs.confidence == 0.8

    def test_cross_modal_observation(self):
        obs = SignalObservation(
            session_id=uuid.uuid4(),
            modality=Modality.cross_modal,
            signal_key="cross_modal_supports",
            confidence=0.75,
        )
        assert obs.modality == Modality.cross_modal


# ---------------------------------------------------------------------------
# Content schemas
# ---------------------------------------------------------------------------

class TestContentSchemas:
    def test_topic_mention(self):
        tm = TopicMention(
            topic_key="peer_pressure",
            label="Peer Pressure",
            depth=TopicDepth.moderate,
            turn_indices=[1, 3, 5],
            confidence=0.85,
        )
        assert tm.depth == TopicDepth.moderate
        assert len(tm.turn_indices) == 3

    def test_avoidance_event(self):
        ae = AvoidanceEvent(
            topic_key="family",
            turn_index=4,
            trigger_text="Tell me about your family",
            avoidance_text="Let's talk about something else",
            confidence=0.7,
        )
        assert ae.turn_index == 4

    def test_hedging_marker(self):
        hm = HedgingMarker(
            turn_index=3,
            text="I think maybe",
            hedge_type="qualifier",
            confidence=0.8,
        )
        assert hm.hedge_type == "qualifier"

    def test_agency_marker(self):
        am = AgencyMarker(
            turn_index=5,
            text="I want to be a doctor",
            level=AgencyLevel.high,
            direction="self",
            confidence=0.9,
        )
        assert am.level == AgencyLevel.high

    def test_content_features_roundtrip(self, session_id, sample_content_features):
        features = ContentFeatures(**sample_content_features)
        data = json.loads(features.model_dump_json())
        restored = ContentFeatures(**data)
        assert restored.reliability_score == 0.85
        assert len(restored.topics) == 2
        assert len(restored.hedging_markers) == 2


# ---------------------------------------------------------------------------
# Audio schemas
# ---------------------------------------------------------------------------

class TestAudioSchemas:
    def test_pause_event(self):
        pe = PauseEvent(
            start_ms=12000,
            end_ms=12500,
            duration_ms=500,
            turn_index=3,
            is_inter_turn=False,
        )
        assert pe.duration_ms == 500

    def test_dysfluency_event(self):
        de = DysfluencyEvent(
            turn_index=7,
            dysfluency_type=DysfluencyType.filler,
            confidence=0.65,
        )
        assert de.dysfluency_type == DysfluencyType.filler

    def test_turn_audio_features(self):
        taf = TurnAudioFeatures(
            turn_index=3,
            start_ms=19500,
            end_ms=28000,
            speech_rate_wpm=95.0,
            pitch_mean_hz=195.0,
            confidence_score=0.45,
        )
        assert taf.speech_rate_wpm == 95.0
        assert taf.confidence_score == 0.45

    def test_audio_features_roundtrip(self, session_id, sample_audio_features):
        features = AudioFeatures(**sample_audio_features)
        data = json.loads(features.model_dump_json())
        restored = AudioFeatures(**data)
        assert restored.reliability_score == 0.75
        assert len(restored.turn_features) == 4
        assert len(restored.pauses) == 3
        assert len(restored.dysfluencies) == 3


# ---------------------------------------------------------------------------
# Video schemas
# ---------------------------------------------------------------------------

class TestVideoSchemas:
    def test_face_presence_segment(self):
        fps = FacePresenceSegment(
            start_ms=0,
            end_ms=5000,
            face_detected=True,
            face_confidence=0.95,
        )
        assert fps.face_detected is True

    def test_engagement_enum(self):
        assert EngagementLevel.disengaged.value == "disengaged"
        assert EngagementLevel.highly_engaged.value == "highly_engaged"

    def test_gaze_enum(self):
        assert GazeDirection.direct.value == "direct"
        assert GazeDirection.averted_left.value == "averted_left"

    def test_movement_enum(self):
        assert MovementType.fidgeting.value == "fidgeting"
        assert MovementType.lean_forward.value == "lean_forward"


# ---------------------------------------------------------------------------
# Cross-modal enum coverage
# ---------------------------------------------------------------------------

class TestModalityEnums:
    def test_all_modalities(self):
        assert len(Modality) == 4
        assert Modality.cross_modal.value == "cross_modal"

    def test_observation_sources(self):
        assert len(ObservationSource) >= 3
        assert ObservationSource.deterministic.value == "deterministic"
