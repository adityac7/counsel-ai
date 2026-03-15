"""Pydantic models for all API request/response contracts."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------
class SessionStatus(str, Enum):
    draft = "draft"
    live = "live"
    uploaded = "uploaded"
    processing = "processing"
    completed = "completed"
    failed = "failed"


class Speaker(str, Enum):
    student = "student"
    counsellor = "counsellor"
    system = "system"


class HypothesisStatus(str, Enum):
    supported = "supported"
    mixed = "mixed"
    weak = "weak"


class RedFlagSeverity(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"


# ---------------------------------------------------------------------------
# Live session contracts
# ---------------------------------------------------------------------------
class SessionCreateRequest(BaseModel):
    student_id: uuid.UUID
    case_study_id: str
    provider: str = "gemini-live"


class SessionCreateResponse(BaseModel):
    session_id: uuid.UUID
    status: SessionStatus = SessionStatus.draft


class SessionCompleteResponse(BaseModel):
    session_id: uuid.UUID
    status: SessionStatus = SessionStatus.processing
    job_id: uuid.UUID


# ---------------------------------------------------------------------------
# WebSocket event envelopes
# ---------------------------------------------------------------------------
class InboundMediaChunk(BaseModel):
    type: str = "media_chunk"
    timestamp_ms: int
    mime_type: str
    data_b64: str


class OutboundTranscriptTurn(BaseModel):
    type: str = "transcript_turn"
    speaker: Speaker
    turn_index: int
    start_ms: int
    end_ms: int
    text: str


# ---------------------------------------------------------------------------
# Session detail
# ---------------------------------------------------------------------------
class SessionDetailResponse(BaseModel):
    session_id: uuid.UUID
    student_id: uuid.UUID
    case_study_id: str
    provider: str
    status: SessionStatus
    started_at: datetime
    ended_at: datetime | None = None
    duration_seconds: int | None = None
    primary_language: str | None = None
    processing_version: str


# ---------------------------------------------------------------------------
# Profile / hypothesis contracts
# ---------------------------------------------------------------------------
class ConstructOut(BaseModel):
    key: str
    label: str
    status: HypothesisStatus
    score: float | None = None
    evidence_refs: list[str] = Field(default_factory=list)


class RedFlagOut(BaseModel):
    key: str
    severity: RedFlagSeverity
    reason: str


class ProfileResponse(BaseModel):
    session_id: uuid.UUID
    summary: str
    constructs: list[ConstructOut] = Field(default_factory=list)
    red_flags: list[RedFlagOut] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Dashboard contracts
# ---------------------------------------------------------------------------
class SessionQueueItem(BaseModel):
    session_id: uuid.UUID
    student_name: str
    school_name: str | None = None
    status: SessionStatus
    red_flag_count: int = 0
    started_at: datetime


class CounsellorQueueResponse(BaseModel):
    items: list[SessionQueueItem] = Field(default_factory=list)
    total: int = 0


class StudentSessionSummary(BaseModel):
    session_id: uuid.UUID
    case_study_id: str
    status: SessionStatus
    started_at: datetime
    summary: str | None = None


class StudentDashboardResponse(BaseModel):
    student_id: uuid.UUID
    full_name: str
    sessions: list[StudentSessionSummary] = Field(default_factory=list)
    latest_profile: ProfileResponse | None = None


class CohortStat(BaseModel):
    label: str
    count: int


# ---------------------------------------------------------------------------
# School analytics contracts (Task 14)
# ---------------------------------------------------------------------------
class GradeDistribution(BaseModel):
    grade: str
    student_count: int = 0
    session_count: int = 0


class SectionDistribution(BaseModel):
    grade: str
    section: str = "—"
    student_count: int = 0
    session_count: int = 0


class RedFlagSummary(BaseModel):
    total_flags: int = 0
    by_severity: dict[str, int] = Field(default_factory=dict)
    by_key: dict[str, int] = Field(default_factory=dict)


class TopicCluster(BaseModel):
    topic_key: str
    occurrences: int = 0
    avg_reliability: float | None = None


class ConstructAggregate(BaseModel):
    construct_key: str
    label: str
    total: int = 0
    supported: int = 0
    mixed: int = 0
    weak: int = 0
    avg_score: float | None = None


class TrendPoint(BaseModel):
    period: str | None = None
    session_count: int = 0
    unique_students: int = 0


class TopicCount(BaseModel):
    topic_key: str
    count: int = 0


class ClassInsights(BaseModel):
    grade: str
    student_count: int = 0
    session_count: int = 0
    completed_sessions: int = 0
    red_flag_total: int = 0
    top_topics: list[TopicCount] = Field(default_factory=list)


class BatchSummary(BaseModel):
    by_status: dict[str, int] = Field(default_factory=dict)


class SchoolOverviewResponse(BaseModel):
    school_id: uuid.UUID
    name: str
    board: str | None = None
    city: str | None = None
    total_students: int = 0
    total_sessions: int = 0
    completed_sessions: int = 0
    avg_duration_seconds: float | None = None
    cohort_stats: list[CohortStat] = Field(default_factory=list)
    grade_distribution: list[GradeDistribution] = Field(default_factory=list)
    section_distribution: list[SectionDistribution] = Field(default_factory=list)
    red_flag_summary: RedFlagSummary = Field(default_factory=RedFlagSummary)
    topic_clusters: list[TopicCluster] = Field(default_factory=list)
    construct_distribution: list[ConstructAggregate] = Field(default_factory=list)
    session_trend: list[TrendPoint] = Field(default_factory=list)
    batch_summary: BatchSummary = Field(default_factory=BatchSummary)
    class_insights: ClassInsights | None = None


# ---------------------------------------------------------------------------
# Session report contracts
# ---------------------------------------------------------------------------
class ThemeItem(BaseModel):
    theme: str
    evidence: str = ""


class EmotionalIndicators(BaseModel):
    primary_emotion: str = ""
    secondary_emotions: list[str] = Field(default_factory=list)
    trajectory: str = ""
    emotional_vocabulary_level: str = ""


class RiskFlags(BaseModel):
    level: str = "none"
    flags: list[str] = Field(default_factory=list)
    protective_factors: list[str] = Field(default_factory=list)
    immediate_safety_concern: bool = False


class CounsellorEffectiveness(BaseModel):
    listen_phase: str = ""
    probe_phase: str = ""
    dig_deeper_phase: str = ""
    pattern_followed: bool = False
    strengths: list[str] = Field(default_factory=list)
    areas_to_improve: list[str] = Field(default_factory=list)


class RecommendedFollowups(BaseModel):
    actions: list[str] = Field(default_factory=list)
    topics_for_next_session: list[str] = Field(default_factory=list)
    referral_needed: bool = False
    referral_type: str = "none"
    urgency: str = "routine"


class CognitiveProfileSnapshot(BaseModel):
    decision_making_style: str = ""
    emotional_regulation: str = ""
    social_awareness: str = ""
    self_awareness: str = ""
    coping_strategies: list[str] = Field(default_factory=list)


class SessionReportResponse(BaseModel):
    session_id: uuid.UUID
    session_summary: str = ""
    student_engagement_score: int = 0
    student_engagement_rationale: str = ""
    key_themes: list[ThemeItem] = Field(default_factory=list)
    emotional_indicators: EmotionalIndicators = Field(
        default_factory=EmotionalIndicators
    )
    risk_flags: RiskFlags = Field(default_factory=RiskFlags)
    counsellor_effectiveness: CounsellorEffectiveness = Field(
        default_factory=CounsellorEffectiveness
    )
    recommended_followups: RecommendedFollowups = Field(
        default_factory=RecommendedFollowups
    )
    cognitive_profile_snapshot: CognitiveProfileSnapshot = Field(
        default_factory=CognitiveProfileSnapshot
    )


# ---------------------------------------------------------------------------
# Worker payload
# ---------------------------------------------------------------------------
class ProcessingStep(str, Enum):
    canonicalize = "canonicalize"
    content = "content"
    audio = "audio"
    video = "video"
    correlate = "correlate"
    profile = "profile"


class JobPayload(BaseModel):
    session_id: uuid.UUID
    processing_version: str = "v1"
    steps: list[ProcessingStep] = Field(
        default_factory=lambda: list(ProcessingStep)
    )
