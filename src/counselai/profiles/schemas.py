"""Pydantic schemas for profile synthesis inputs, outputs, and validation.

These models define the bounded profile contracts used by the synthesis
engine, LLM prompt builders, validators, and the API layer.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Shared enums (re-exported for convenience; canonical source is api/schemas.py)
# ---------------------------------------------------------------------------

class HypothesisStatus(str, Enum):
    supported = "supported"
    mixed = "mixed"
    weak = "weak"


class RedFlagSeverity(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"


# ---------------------------------------------------------------------------
# Evidence reference models
# ---------------------------------------------------------------------------

class EvidenceRef(BaseModel):
    """A reference to a specific piece of supporting evidence."""
    ref_type: str = Field(
        ..., description="Type of reference: 'turn', 'window', 'audio', 'video', 'content'"
    )
    ref_id: str = Field(..., description="Identifier, e.g. 'turn:7' or 'window:career_interest'")
    modality: str | None = Field(None, description="Signal modality if applicable")
    summary: str | None = Field(None, description="Brief description of the evidence")
    confidence: float = Field(0.0, ge=0.0, le=1.0)


# ---------------------------------------------------------------------------
# Construct (hypothesis) models
# ---------------------------------------------------------------------------

class Construct(BaseModel):
    """A psychological/behavioral construct assessed from the session."""
    key: str = Field(..., description="Canonical construct key, e.g. 'career_identity_clarity'")
    label: str = Field(..., description="Human-readable label")
    status: HypothesisStatus = HypothesisStatus.weak
    score: float | None = Field(None, ge=0.0, le=1.0)
    evidence_summary: str = Field("", description="Brief narrative explaining the assessment")
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)
    supporting_quotes: list[str] = Field(
        default_factory=list, description="Direct quotes from the student"
    )


class RedFlag(BaseModel):
    """A concern or risk indicator requiring counsellor attention."""
    key: str = Field(..., description="Canonical red flag key, e.g. 'high_external_pressure'")
    severity: RedFlagSeverity = RedFlagSeverity.medium
    reason: str = Field(..., description="Why this flag was raised")
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)
    recommended_action: str | None = Field(
        None, description="Suggested follow-up for the counsellor"
    )


# ---------------------------------------------------------------------------
# Role-specific profile views
# ---------------------------------------------------------------------------

class StudentProfileView(BaseModel):
    """Student-facing profile: strengths, interests, growth, next steps.

    Deliberately avoids clinical language, risk scores, and red flags.
    """
    strengths: list[str] = Field(default_factory=list)
    interests: list[str] = Field(default_factory=list)
    growth_areas: list[str] = Field(default_factory=list)
    suggested_next_steps: list[str] = Field(default_factory=list)
    summary: str = ""
    encouragement: str = Field(
        "", description="Positive, non-diagnostic closing message"
    )


class CounsellorProfileView(BaseModel):
    """Counsellor-facing profile: full constructs, evidence, and red flags."""
    summary: str = ""
    constructs: list[Construct] = Field(default_factory=list)
    red_flags: list[RedFlag] = Field(default_factory=list)
    cross_modal_notes: list[str] = Field(
        default_factory=list,
        description="Notable agreements/contradictions across modalities",
    )
    recommended_follow_ups: list[str] = Field(default_factory=list)


class SchoolProfileView(BaseModel):
    """School-facing profile: aggregate-safe, no individual clinical detail."""
    primary_topics: list[str] = Field(default_factory=list)
    risk_level: RedFlagSeverity | None = None
    engagement_rating: str | None = Field(
        None, description="Qualitative engagement: low, moderate, high"
    )
    summary: str = ""


# ---------------------------------------------------------------------------
# Full profile output
# ---------------------------------------------------------------------------

class SessionProfile(BaseModel):
    """Complete profile output for a session.

    Serialized to: artifacts/sessions/<session_id>/analysis/profile.json
    Stored in DB: profiles table (student_view_json, counsellor_view_json, etc.)
    """
    session_id: uuid.UUID
    profile_version: str = "v1"
    student_view: StudentProfileView = Field(default_factory=StudentProfileView)
    counsellor_view: CounsellorProfileView = Field(default_factory=CounsellorProfileView)
    school_view: SchoolProfileView = Field(default_factory=SchoolProfileView)
    red_flags: list[RedFlag] = Field(default_factory=list)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(tz=__import__("datetime").timezone.utc)
    )


# ---------------------------------------------------------------------------
# LLM synthesis request/response models
# ---------------------------------------------------------------------------

class SynthesisRequest(BaseModel):
    """Input payload sent to the profile synthesis LLM."""
    session_id: uuid.UUID
    transcript_summary: str = ""
    content_features_json: str = Field("", description="Serialized ContentFeatures")
    audio_features_json: str = Field("", description="Serialized AudioFeatures")
    video_features_json: str = Field("", description="Serialized VideoFeatures")
    evidence_graph_json: str = Field("", description="Serialized evidence graph")
    student_context: str | None = Field(
        None, description="Prior session context if available"
    )


class SynthesisResponse(BaseModel):
    """Raw LLM output for profile synthesis, before validation."""
    session_id: uuid.UUID
    raw_output: str = Field("", description="Raw LLM text output")
    parsed_profile: SessionProfile | None = None
    validation_errors: list[str] = Field(default_factory=list)
    is_valid: bool = False
