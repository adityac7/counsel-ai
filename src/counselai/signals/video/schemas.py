"""Pydantic schemas for video signal extraction outputs.

These models represent structured video features: face presence,
gaze proxy, posture/engagement estimates, facial tension events,
and movement events — aligned to turns and topic windows.
"""

from __future__ import annotations

import uuid
from enum import Enum

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class EngagementLevel(str, Enum):
    """Estimated engagement level from posture/gaze."""
    disengaged = "disengaged"
    passive = "passive"
    engaged = "engaged"
    highly_engaged = "highly_engaged"


class MovementType(str, Enum):
    """Types of notable body movement events."""
    lean_forward = "lean_forward"
    lean_back = "lean_back"
    head_turn = "head_turn"
    hand_gesture = "hand_gesture"
    fidgeting = "fidgeting"
    posture_shift = "posture_shift"
    face_touch = "face_touch"


class GazeDirection(str, Enum):
    """Approximate gaze direction relative to camera."""
    direct = "direct"
    averted_left = "averted_left"
    averted_right = "averted_right"
    downward = "downward"
    upward = "upward"
    unknown = "unknown"


# ---------------------------------------------------------------------------
# Per-turn / per-frame features
# ---------------------------------------------------------------------------

class FacePresenceSegment(BaseModel):
    """A contiguous segment where a face was or was not detected."""
    start_ms: int
    end_ms: int
    face_detected: bool = True
    face_confidence: float = Field(0.0, ge=0.0, le=1.0)
    face_count: int = Field(1, ge=0, description="Number of faces in frame")


class GazeObservation(BaseModel):
    """Gaze direction observation for a time segment."""
    start_ms: int
    end_ms: int
    direction: GazeDirection = GazeDirection.unknown
    turn_index: int | None = None
    confidence: float = Field(0.0, ge=0.0, le=1.0)


class TensionEvent(BaseModel):
    """A detected facial tension event (jaw clench, brow furrow, etc.)."""
    timestamp_ms: int
    turn_index: int | None = None
    region: str = Field(..., description="Face region: jaw, brow, mouth, eye")
    intensity: float = Field(0.0, ge=0.0, le=1.0)
    confidence: float = Field(0.0, ge=0.0, le=1.0)


class MovementEvent(BaseModel):
    """A notable body/head movement event."""
    start_ms: int
    end_ms: int | None = None
    turn_index: int | None = None
    movement_type: MovementType
    magnitude: float | None = Field(None, ge=0.0, le=1.0)
    confidence: float = Field(0.0, ge=0.0, le=1.0)


class TurnVideoFeatures(BaseModel):
    """Video features aggregated for a single turn."""
    turn_index: int
    start_ms: int
    end_ms: int
    face_visible_pct: float = Field(
        0.0, ge=0.0, le=100.0,
        description="Percentage of turn duration where face was visible",
    )
    dominant_gaze: GazeDirection = GazeDirection.unknown
    engagement_estimate: EngagementLevel = EngagementLevel.passive
    tension_event_count: int = 0
    movement_event_count: int = 0


# ---------------------------------------------------------------------------
# Window-level video summary
# ---------------------------------------------------------------------------

class WindowVideoSummary(BaseModel):
    """Aggregated video features for a topic window."""
    window_id: uuid.UUID | None = None
    topic_key: str | None = None
    start_ms: int
    end_ms: int
    avg_face_visible_pct: float = 0.0
    dominant_gaze: GazeDirection = GazeDirection.unknown
    engagement_estimate: EngagementLevel = EngagementLevel.passive
    tension_density: float = Field(
        0.0, description="Tension events per minute within the window"
    )
    movement_density: float = Field(
        0.0, description="Movement events per minute within the window"
    )


# ---------------------------------------------------------------------------
# Aggregated video features output
# ---------------------------------------------------------------------------

class VideoFeatures(BaseModel):
    """Complete video signal extraction output for a session.

    Serialized to: artifacts/sessions/<session_id>/features/video.json
    """
    session_id: uuid.UUID
    face_presence: list[FacePresenceSegment] = Field(default_factory=list)
    gaze_observations: list[GazeObservation] = Field(default_factory=list)
    tension_events: list[TensionEvent] = Field(default_factory=list)
    movement_events: list[MovementEvent] = Field(default_factory=list)
    turn_features: list[TurnVideoFeatures] = Field(default_factory=list)
    window_summaries: list[WindowVideoSummary] = Field(default_factory=list)
    total_face_visible_pct: float = Field(
        0.0, ge=0.0, le=100.0,
        description="Session-wide face visibility percentage",
    )
    video_duration_ms: int | None = None
    frame_count: int | None = None
    reliability_score: float = Field(
        0.0, ge=0.0, le=1.0,
        description="Video quality reliability (low face visibility, poor lighting → low score)",
    )
