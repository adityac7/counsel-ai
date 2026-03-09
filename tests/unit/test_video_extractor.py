"""Tests for the video signal extractor.

Covers: graceful degradation, frame analysis, engagement classification,
movement detection, turn/window aggregation, reliability scoring.
"""

from __future__ import annotations

import json
import tempfile
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import cv2
import numpy as np
import pytest

from counselai.signals.video.extractor import (
    FRAME_SAMPLE_INTERVAL_SEC,
    _classify_engagement,
    _compute_reliability,
    _detect_movements,
    _is_blurry,
    _build_turn_features,
    _find_turn_index,
    extract_frames,
    extract_video_signals,
)
from counselai.signals.video.schemas import (
    EngagementLevel,
    FacePresenceSegment,
    GazeDirection,
    GazeObservation,
    MovementEvent,
    MovementType,
    TensionEvent,
    TurnVideoFeatures,
    VideoFeatures,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_video(tmp_path: Path) -> Path:
    """Create a minimal test video file (5 seconds, 10fps, 320x240)."""
    video_path = tmp_path / "test_video.mp4"
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(video_path), fourcc, 10.0, (320, 240))
    for i in range(50):  # 5 seconds at 10fps
        # Create frames with varying content
        frame = np.zeros((240, 320, 3), dtype=np.uint8)
        # Add some texture to avoid pure-black blurry detection
        cv2.putText(frame, f"Frame {i}", (50, 120),
                     cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2)
        cv2.circle(frame, (160, 120), 50 + i, (0, 255, 0), 2)
        writer.write(frame)
    writer.release()
    return video_path


@pytest.fixture
def sample_turns() -> list[dict]:
    return [
        {"turn_index": 0, "start_ms": 0, "end_ms": 2000},
        {"turn_index": 1, "start_ms": 2000, "end_ms": 4000},
        {"turn_index": 2, "start_ms": 4000, "end_ms": 5000},
    ]


@pytest.fixture
def sample_windows() -> list[dict]:
    return [
        {"id": str(uuid.uuid4()), "topic_key": "intro", "start_ms": 0, "end_ms": 3000},
        {"id": str(uuid.uuid4()), "topic_key": "main", "start_ms": 3000, "end_ms": 5000},
    ]


# ---------------------------------------------------------------------------
# Test: missing/invalid video
# ---------------------------------------------------------------------------

class TestGracefulDegradation:
    def test_missing_video_returns_empty_features(self, tmp_path):
        """When no video exists, return empty features with 0 reliability."""
        sid = str(uuid.uuid4())
        from counselai.ingest.artifact_store import ArtifactStore
        store = ArtifactStore(root=tmp_path / "artifacts")

        features = extract_video_signals(
            session_id=sid,
            video_path=None,
            artifact_store=store,
        )

        assert isinstance(features, VideoFeatures)
        assert features.reliability_score == 0.0
        assert features.frame_count is None
        assert features.face_presence == []
        assert features.gaze_observations == []

    def test_nonexistent_path_returns_empty(self, tmp_path):
        sid = str(uuid.uuid4())
        from counselai.ingest.artifact_store import ArtifactStore
        store = ArtifactStore(root=tmp_path / "artifacts")

        features = extract_video_signals(
            session_id=sid,
            video_path="/nonexistent/video.mp4",
            artifact_store=store,
        )

        assert features.reliability_score == 0.0

    def test_corrupt_video_returns_empty(self, tmp_path):
        sid = str(uuid.uuid4())
        corrupt = tmp_path / "corrupt.mp4"
        corrupt.write_bytes(b"not a video file")

        from counselai.ingest.artifact_store import ArtifactStore
        store = ArtifactStore(root=tmp_path / "artifacts")

        features = extract_video_signals(
            session_id=sid,
            video_path=str(corrupt),
            artifact_store=store,
        )

        assert features.reliability_score == 0.0
        assert features.frame_count is None or features.frame_count == 0


# ---------------------------------------------------------------------------
# Test: frame extraction
# ---------------------------------------------------------------------------

class TestFrameExtraction:
    def test_extracts_frames(self, tmp_video):
        frames = extract_frames(tmp_video, interval_sec=1.0)
        # 5 second video at 10fps, 1 frame/sec = ~5 frames
        assert len(frames) >= 4
        assert len(frames) <= 6

        # Each frame has (timestamp_ms, ndarray)
        for ts, frame in frames:
            assert isinstance(ts, int)
            assert ts >= 0
            assert isinstance(frame, np.ndarray)
            assert frame.shape[0] > 0

    def test_empty_path_returns_empty(self):
        frames = extract_frames("/nonexistent/path.mp4")
        assert frames == []


# ---------------------------------------------------------------------------
# Test: blur detection
# ---------------------------------------------------------------------------

class TestBlurDetection:
    def test_blank_frame_is_blurry(self):
        blank = np.zeros((240, 320, 3), dtype=np.uint8)
        assert _is_blurry(blank) is True

    def test_textured_frame_not_blurry(self):
        frame = np.random.randint(0, 255, (240, 320, 3), dtype=np.uint8)
        assert _is_blurry(frame) is False


# ---------------------------------------------------------------------------
# Test: engagement classification
# ---------------------------------------------------------------------------

class TestEngagementClassification:
    def test_direct_gaze_high_posture(self):
        face = {"face_detected": True, "gaze_direction": GazeDirection.direct}
        pose = {"vertical_offset": 0.25}
        result = _classify_engagement(face, pose)
        assert result in (EngagementLevel.engaged, EngagementLevel.highly_engaged)

    def test_no_face_is_disengaged(self):
        face = {"face_detected": False}
        result = _classify_engagement(face, None)
        assert result in (EngagementLevel.disengaged, EngagementLevel.passive)

    def test_none_inputs_returns_low_engagement(self):
        result = _classify_engagement(None, None)
        # No face, no pose → disengaged or passive
        assert result in (EngagementLevel.disengaged, EngagementLevel.passive)

    def test_averted_gaze_reduces_engagement(self):
        face = {"face_detected": True, "gaze_direction": GazeDirection.averted_left}
        result = _classify_engagement(face, None)
        assert result in (EngagementLevel.passive, EngagementLevel.disengaged)


# ---------------------------------------------------------------------------
# Test: movement detection
# ---------------------------------------------------------------------------

class TestMovementDetection:
    def test_lean_forward_detected(self):
        history = [
            (0, {"vertical_offset": 0.18, "horizontal_offset": 0.0, "shoulder_width": 0.3,
                 "shoulder_mid_y": 0.5, "nose_y": 0.3, "nose_x": 0.5}),
            (1000, {"vertical_offset": 0.28, "horizontal_offset": 0.0, "shoulder_width": 0.3,
                    "shoulder_mid_y": 0.5, "nose_y": 0.22, "nose_x": 0.5}),
        ]
        events = _detect_movements(history)
        lean_events = [e for e in events if e.movement_type == MovementType.lean_forward]
        assert len(lean_events) >= 1

    def test_head_turn_detected(self):
        history = [
            (0, {"vertical_offset": 0.2, "horizontal_offset": 0.0, "shoulder_width": 0.3,
                 "shoulder_mid_y": 0.5, "nose_y": 0.3, "nose_x": 0.5}),
            (1000, {"vertical_offset": 0.2, "horizontal_offset": 0.08, "shoulder_width": 0.3,
                    "shoulder_mid_y": 0.5, "nose_y": 0.3, "nose_x": 0.58}),
        ]
        events = _detect_movements(history)
        head_events = [e for e in events if e.movement_type == MovementType.head_turn]
        assert len(head_events) >= 1

    def test_no_movement_when_stable(self):
        history = [
            (0, {"vertical_offset": 0.2, "horizontal_offset": 0.0, "shoulder_width": 0.3,
                 "shoulder_mid_y": 0.5, "nose_y": 0.3, "nose_x": 0.5}),
            (1000, {"vertical_offset": 0.2, "horizontal_offset": 0.01, "shoulder_width": 0.3,
                    "shoulder_mid_y": 0.5, "nose_y": 0.3, "nose_x": 0.51}),
        ]
        events = _detect_movements(history)
        # Only fidgeting/posture_shift with very small magnitude possible, no big movements
        big_events = [e for e in events if e.movement_type in (
            MovementType.lean_forward, MovementType.lean_back,
            MovementType.head_turn,
        )]
        assert len(big_events) == 0

    def test_empty_history(self):
        assert _detect_movements([]) == []
        assert _detect_movements([(0, None)]) == []


# ---------------------------------------------------------------------------
# Test: turn index lookup
# ---------------------------------------------------------------------------

class TestTurnLookup:
    def test_finds_correct_turn(self, sample_turns):
        assert _find_turn_index(500, sample_turns) == 0
        assert _find_turn_index(2500, sample_turns) == 1
        assert _find_turn_index(4500, sample_turns) == 2

    def test_out_of_range_returns_none(self, sample_turns):
        assert _find_turn_index(6000, sample_turns) is None

    def test_empty_turns(self):
        assert _find_turn_index(500, []) is None


# ---------------------------------------------------------------------------
# Test: reliability scoring
# ---------------------------------------------------------------------------

class TestReliability:
    def test_perfect_video(self):
        score = _compute_reliability(100, 100, 95, 0, 60_000)
        assert score >= 0.85

    def test_no_frames(self):
        score = _compute_reliability(0, 0, 0, 0, None)
        assert score == 0.0

    def test_all_blurry(self):
        score = _compute_reliability(100, 0, 0, 100, 30_000)
        assert score < 0.3

    def test_no_faces(self):
        score = _compute_reliability(100, 80, 0, 20, 60_000)
        assert score <= 0.5

    def test_short_video_penalty(self):
        long = _compute_reliability(100, 90, 80, 10, 120_000)
        short = _compute_reliability(100, 90, 80, 10, 5_000)
        assert long > short


# ---------------------------------------------------------------------------
# Test: turn features aggregation
# ---------------------------------------------------------------------------

class TestTurnFeatures:
    def test_builds_features_for_each_turn(self, sample_turns):
        face_segs = [
            FacePresenceSegment(start_ms=0, end_ms=3000, face_detected=True, face_confidence=0.9),
            FacePresenceSegment(start_ms=3000, end_ms=5000, face_detected=False, face_confidence=0.0),
        ]
        gaze_obs = [
            GazeObservation(start_ms=500, end_ms=1500, direction=GazeDirection.direct,
                           turn_index=0, confidence=0.8),
        ]
        engagement_map = {0: EngagementLevel.engaged, 1: EngagementLevel.passive}

        features = _build_turn_features(
            sample_turns, face_segs, gaze_obs, [], [], engagement_map,
        )

        assert len(features) == 3
        assert features[0].turn_index == 0
        assert features[0].face_visible_pct > 0
        assert features[0].dominant_gaze == GazeDirection.direct
        assert features[0].engagement_estimate == EngagementLevel.engaged
        # Turn 2 (4000-5000) has no face
        assert features[2].face_visible_pct == 0.0


# ---------------------------------------------------------------------------
# Test: full pipeline (mocked MediaPipe + no Gemini)
# ---------------------------------------------------------------------------

class TestFullPipeline:
    def test_pipeline_with_video(self, tmp_video, tmp_path, sample_turns):
        """Full pipeline produces valid VideoFeatures."""
        from counselai.ingest.artifact_store import ArtifactStore
        store = ArtifactStore(root=tmp_path / "artifacts")

        sid = str(uuid.uuid4())

        # Mock MediaPipe to avoid needing real faces
        with patch("counselai.signals.video.extractor._analyze_face") as mock_face, \
             patch("counselai.signals.video.extractor._analyze_pose") as mock_pose:

            mock_face.return_value = {
                "face_detected": True,
                "face_confidence": 0.9,
                "gaze_direction": GazeDirection.direct,
                "gaze_confidence": 0.8,
                "tension_regions": [],
            }
            mock_pose.return_value = {
                "vertical_offset": 0.22,
                "horizontal_offset": 0.01,
                "shoulder_width": 0.3,
                "shoulder_mid_y": 0.5,
                "nose_y": 0.28,
                "nose_x": 0.5,
            }

            features = extract_video_signals(
                session_id=sid,
                video_path=str(tmp_video),
                turns=sample_turns,
                use_gemini=False,
                artifact_store=store,
            )

        assert isinstance(features, VideoFeatures)
        assert features.frame_count >= 4
        assert features.reliability_score > 0
        assert features.total_face_visible_pct > 0
        assert len(features.face_presence) > 0
        assert len(features.gaze_observations) > 0
        assert len(features.turn_features) == 3

        # Check artifact was written
        video_json = store.read_json(sid, "features/video.json")
        assert video_json is not None
        assert video_json["session_id"] == sid

    def test_pipeline_no_video(self, tmp_path):
        """Pipeline with no video returns empty features gracefully."""
        from counselai.ingest.artifact_store import ArtifactStore
        store = ArtifactStore(root=tmp_path / "artifacts")
        sid = str(uuid.uuid4())

        features = extract_video_signals(
            session_id=sid,
            video_path=None,
            use_gemini=False,
            artifact_store=store,
        )

        assert features.reliability_score == 0.0
        assert features.face_presence == []


# ---------------------------------------------------------------------------
# Test: schema serialization
# ---------------------------------------------------------------------------

class TestSchemaSerialization:
    def test_video_features_round_trip(self):
        sid = uuid.uuid4()
        features = VideoFeatures(
            session_id=sid,
            face_presence=[
                FacePresenceSegment(start_ms=0, end_ms=1000, face_detected=True, face_confidence=0.9),
            ],
            gaze_observations=[
                GazeObservation(start_ms=0, end_ms=1000, direction=GazeDirection.direct, confidence=0.8),
            ],
            tension_events=[
                TensionEvent(timestamp_ms=500, region="brow", intensity=0.6, confidence=0.5),
            ],
            movement_events=[
                MovementEvent(start_ms=0, end_ms=1000, movement_type=MovementType.lean_forward,
                             magnitude=0.5, confidence=0.7),
            ],
            reliability_score=0.85,
        )

        data = features.model_dump(mode="json")
        restored = VideoFeatures.model_validate(data)

        assert restored.session_id == sid
        assert len(restored.face_presence) == 1
        assert restored.face_presence[0].face_detected is True
        assert restored.reliability_score == 0.85
