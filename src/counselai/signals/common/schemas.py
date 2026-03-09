"""Shared schemas for signal alignment, normalization, and reliability scoring.

Used across content, audio, and video signal modules for
cross-modal alignment on the turn/topic timeline.
"""

from __future__ import annotations

import uuid
from enum import Enum

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class Modality(str, Enum):
    """Signal modality types."""
    content = "content"
    audio = "audio"
    video = "video"
    cross_modal = "cross_modal"


class ObservationSource(str, Enum):
    """How a signal observation was produced."""
    deterministic = "deterministic"
    llm_extracted = "llm_extracted"
    model_inferred = "model_inferred"
    manual = "manual"


# ---------------------------------------------------------------------------
# Timeline alignment
# ---------------------------------------------------------------------------

class TimeSpan(BaseModel):
    """A millisecond-precision time range."""
    start_ms: int = Field(..., ge=0)
    end_ms: int = Field(..., ge=0)

    @property
    def duration_ms(self) -> int:
        return max(0, self.end_ms - self.start_ms)


class TopicWindow(BaseModel):
    """A topic-based time window linking turns and signals."""
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    session_id: uuid.UUID
    topic_key: str
    start_ms: int = Field(..., ge=0)
    end_ms: int = Field(..., ge=0)
    source_turn_ids: list[uuid.UUID] = Field(default_factory=list)
    source_turn_indices: list[int] = Field(
        default_factory=list,
        description="Turn indices covered by this window (convenience field)",
    )
    reliability_score: float = Field(0.0, ge=0.0, le=1.0)


# ---------------------------------------------------------------------------
# Unified observation
# ---------------------------------------------------------------------------

class SignalObservation(BaseModel):
    """A single signal observation from any modality.

    Maps to the `signal_observations` DB table.
    """
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    session_id: uuid.UUID
    window_id: uuid.UUID | None = None
    turn_index: int | None = None
    modality: Modality
    signal_key: str = Field(..., description="e.g. 'hedging', 'pause_duration', 'gaze_aversion'")
    value_json: dict = Field(default_factory=dict)
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    source: ObservationSource = ObservationSource.deterministic
    evidence_ref_json: dict = Field(default_factory=dict)
    timestamp_ms: int | None = None


# ---------------------------------------------------------------------------
# Reliability scoring
# ---------------------------------------------------------------------------

class ModalityReliability(BaseModel):
    """Reliability assessment for a single modality's signals."""
    modality: Modality
    score: float = Field(0.0, ge=0.0, le=1.0)
    reason: str = ""
    sample_count: int = 0
    coverage_pct: float = Field(
        0.0, ge=0.0, le=100.0,
        description="Percentage of session timeline covered by this modality",
    )


class SessionReliability(BaseModel):
    """Overall reliability assessment for a session's signal extraction."""
    session_id: uuid.UUID
    modalities: list[ModalityReliability] = Field(default_factory=list)
    overall_score: float = Field(0.0, ge=0.0, le=1.0)
    notes: list[str] = Field(default_factory=list)
