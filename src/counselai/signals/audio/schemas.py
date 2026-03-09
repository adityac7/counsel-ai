"""Pydantic schemas for audio signal extraction outputs.

These models represent structured audio features: pause mapping,
speech rate, pitch/energy variation, dysfluency events, and
confidence volatility — all aligned to the turn timeline.
"""

from __future__ import annotations

import uuid
from enum import Enum

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class DysfluencyType(str, Enum):
    """Types of speech dysfluency."""
    repetition = "repetition"
    false_start = "false_start"
    filler = "filler"
    prolongation = "prolongation"
    block = "block"


# ---------------------------------------------------------------------------
# Per-turn audio features
# ---------------------------------------------------------------------------

class PauseEvent(BaseModel):
    """A significant pause in speech."""
    start_ms: int
    end_ms: int
    duration_ms: int = Field(..., ge=0)
    turn_index: int | None = None
    context: str | None = Field(
        None, description="What was being discussed around the pause"
    )
    is_inter_turn: bool = Field(
        False, description="True if the pause is between turns rather than within one"
    )


class DysfluencyEvent(BaseModel):
    """A detected speech dysfluency."""
    turn_index: int
    start_ms: int | None = None
    end_ms: int | None = None
    dysfluency_type: DysfluencyType
    text: str | None = Field(None, description="Transcribed dysfluent segment if available")
    confidence: float = Field(0.0, ge=0.0, le=1.0)


class TurnAudioFeatures(BaseModel):
    """Audio features extracted for a single turn."""
    turn_index: int
    start_ms: int
    end_ms: int
    speech_rate_wpm: float | None = Field(None, description="Words per minute")
    pitch_mean_hz: float | None = None
    pitch_std_hz: float | None = None
    energy_mean_db: float | None = None
    energy_std_db: float | None = None
    pause_count: int = 0
    pause_total_ms: int = 0
    dysfluency_count: int = 0
    confidence_score: float | None = Field(
        None, ge=0.0, le=1.0,
        description="Vocal confidence proxy derived from pitch stability and energy",
    )


# ---------------------------------------------------------------------------
# Window-level audio summary
# ---------------------------------------------------------------------------

class WindowAudioSummary(BaseModel):
    """Aggregated audio features for a topic window."""
    window_id: uuid.UUID | None = None
    topic_key: str | None = None
    start_ms: int
    end_ms: int
    avg_speech_rate_wpm: float | None = None
    avg_pitch_hz: float | None = None
    pitch_variability: float | None = Field(
        None, description="Coefficient of variation of pitch across the window"
    )
    energy_variability: float | None = None
    total_pause_ms: int = 0
    confidence_volatility: float | None = Field(
        None,
        description="Standard deviation of per-turn confidence scores within the window",
    )


# ---------------------------------------------------------------------------
# Aggregated audio features output
# ---------------------------------------------------------------------------

class AudioFeatures(BaseModel):
    """Complete audio signal extraction output for a session.

    Serialized to: artifacts/sessions/<session_id>/features/audio.json
    """
    session_id: uuid.UUID
    turn_features: list[TurnAudioFeatures] = Field(default_factory=list)
    pauses: list[PauseEvent] = Field(default_factory=list)
    dysfluencies: list[DysfluencyEvent] = Field(default_factory=list)
    window_summaries: list[WindowAudioSummary] = Field(default_factory=list)
    session_speech_rate_wpm: float | None = None
    session_pitch_mean_hz: float | None = None
    session_energy_mean_db: float | None = None
    reliability_score: float = Field(
        0.0, ge=0.0, le=1.0,
        description="Audio quality reliability (noise, clipping, silence ratio)",
    )
