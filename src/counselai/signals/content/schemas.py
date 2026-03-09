"""Pydantic schemas for content signal extraction outputs.

These models represent the structured output of content analysis:
topic extraction, avoidance detection, depth scoring, hedging markers,
agency language, and code-switching events.
"""

from __future__ import annotations

import uuid
from enum import Enum

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class TopicDepth(str, Enum):
    """How deeply a topic was explored in conversation."""
    surface = "surface"
    moderate = "moderate"
    deep = "deep"


class AgencyLevel(str, Enum):
    """Degree of self-agency expressed by the student."""
    low = "low"
    moderate = "moderate"
    high = "high"


class CodeSwitchDirection(str, Enum):
    """Direction of language code-switching."""
    hindi_to_english = "hindi_to_english"
    english_to_hindi = "english_to_hindi"
    other = "other"


# ---------------------------------------------------------------------------
# Observation models
# ---------------------------------------------------------------------------

class TopicMention(BaseModel):
    """A single topic identified in the conversation."""
    topic_key: str = Field(..., description="Canonical topic identifier, e.g. 'career_interest'")
    label: str = Field(..., description="Human-readable topic name")
    depth: TopicDepth = TopicDepth.surface
    turn_indices: list[int] = Field(default_factory=list, description="Turns where this topic appeared")
    start_ms: int | None = None
    end_ms: int | None = None
    confidence: float = Field(0.0, ge=0.0, le=1.0)


class AvoidanceEvent(BaseModel):
    """Detected avoidance or deflection of a topic."""
    topic_key: str
    turn_index: int
    trigger_text: str = Field(..., description="Text that prompted the avoidance")
    avoidance_text: str = Field(..., description="The deflecting/avoidant response")
    confidence: float = Field(0.0, ge=0.0, le=1.0)


class HedgingMarker(BaseModel):
    """A hedging or uncertainty marker in student speech."""
    turn_index: int
    start_ms: int | None = None
    end_ms: int | None = None
    text: str = Field(..., description="The hedging phrase, e.g. 'I think maybe'")
    hedge_type: str = Field("general", description="Category: general, qualifier, filler, disclaimer")
    confidence: float = Field(0.0, ge=0.0, le=1.0)


class AgencyMarker(BaseModel):
    """An agency or self-direction indicator in student language."""
    turn_index: int
    text: str
    level: AgencyLevel = AgencyLevel.moderate
    direction: str = Field(
        "self",
        description="Who the agency is directed at: self, parent, peer, authority",
    )
    confidence: float = Field(0.0, ge=0.0, le=1.0)


class CodeSwitchEvent(BaseModel):
    """A language code-switching event (e.g. Hinglish transitions)."""
    turn_index: int
    start_ms: int | None = None
    end_ms: int | None = None
    direction: CodeSwitchDirection = CodeSwitchDirection.other
    trigger_context: str | None = Field(
        None, description="What was being discussed when the switch happened"
    )
    text_before: str = ""
    text_after: str = ""
    confidence: float = Field(0.0, ge=0.0, le=1.0)


# ---------------------------------------------------------------------------
# Aggregated content features output
# ---------------------------------------------------------------------------

class ContentFeatures(BaseModel):
    """Complete content signal extraction output for a session.

    Serialized to: artifacts/sessions/<session_id>/features/content.json
    """
    session_id: uuid.UUID
    topics: list[TopicMention] = Field(default_factory=list)
    avoidance_events: list[AvoidanceEvent] = Field(default_factory=list)
    hedging_markers: list[HedgingMarker] = Field(default_factory=list)
    agency_markers: list[AgencyMarker] = Field(default_factory=list)
    code_switch_events: list[CodeSwitchEvent] = Field(default_factory=list)
    dominant_language: str | None = Field(
        None, description="Primary language detected: 'hi', 'en', 'hinglish'"
    )
    overall_depth: TopicDepth = TopicDepth.surface
    overall_agency: AgencyLevel = AgencyLevel.moderate
    reliability_score: float = Field(
        0.0, ge=0.0, le=1.0,
        description="How reliable the content extraction is (low transcript quality → low score)",
    )
