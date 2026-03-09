"""SQLAlchemy ORM models matching the Phase 3 data model spec."""

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from counselai.storage.db import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _new_uuid() -> uuid.UUID:
    return uuid.uuid4()


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class SessionStatus(str, enum.Enum):
    draft = "draft"
    live = "live"
    uploaded = "uploaded"
    processing = "processing"
    completed = "completed"
    failed = "failed"


class Speaker(str, enum.Enum):
    student = "student"
    counsellor = "counsellor"
    system = "system"


class TranscriptSource(str, enum.Enum):
    live_transcript = "live_transcript"
    fallback_transcript = "fallback_transcript"
    manual = "manual"


class ArtifactType(str, enum.Enum):
    audio_raw = "audio_raw"
    video_raw = "video_raw"
    transcript_raw = "transcript_raw"
    transcript_canonical = "transcript_canonical"
    frame_bundle = "frame_bundle"
    audio_features = "audio_features"
    video_features = "video_features"
    content_features = "content_features"
    evidence_graph = "evidence_graph"
    profile = "profile"


class Modality(str, enum.Enum):
    content = "content"
    audio = "audio"
    video = "video"
    cross_modal = "cross_modal"


class HypothesisStatus(str, enum.Enum):
    supported = "supported"
    mixed = "mixed"
    weak = "weak"


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class School(Base):
    __tablename__ = "schools"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    board: Mapped[str | None] = mapped_column(String(100))
    city: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )

    students: Mapped[list["Student"]] = relationship(back_populates="school")


class Student(Base):
    __tablename__ = "students"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    external_ref: Mapped[str | None] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    grade: Mapped[str] = mapped_column(String(20), nullable=False)
    section: Mapped[str | None] = mapped_column(String(20))
    school_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("schools.id")
    )
    age: Mapped[int | None] = mapped_column(Integer)
    language_pref: Mapped[str | None] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )

    school: Mapped[School | None] = relationship(back_populates="students")
    sessions: Mapped[list["SessionRecord"]] = relationship(back_populates="student")


class SessionRecord(Base):
    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("students.id"), nullable=False
    )
    case_study_id: Mapped[str] = mapped_column(String(100), nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[SessionStatus] = mapped_column(
        Enum(SessionStatus, name="session_status", native_enum=True),
        default=SessionStatus.draft,
        nullable=False,
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_seconds: Mapped[int | None] = mapped_column(Integer)
    artifact_manifest_path: Mapped[str | None] = mapped_column(Text)
    primary_language: Mapped[str | None] = mapped_column(String(20))
    processing_version: Mapped[str | None] = mapped_column(String(20))

    student: Mapped[Student] = relationship(back_populates="sessions")
    turns: Mapped[list["Turn"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )
    artifacts: Mapped[list["Artifact"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )
    signal_windows: Mapped[list["SignalWindow"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )
    signal_observations: Mapped[list["SignalObservation"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )
    hypotheses: Mapped[list["Hypothesis"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )
    profiles: Mapped[list["Profile"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )


class Turn(Base):
    __tablename__ = "turns"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sessions.id"), nullable=False
    )
    turn_index: Mapped[int] = mapped_column(Integer, nullable=False)
    speaker: Mapped[Speaker] = mapped_column(
        Enum(Speaker, name="speaker_type", native_enum=True), nullable=False
    )
    start_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    end_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[TranscriptSource] = mapped_column(
        Enum(TranscriptSource, name="transcript_source", native_enum=True),
        nullable=False,
    )
    confidence: Mapped[float | None] = mapped_column(Float)

    session: Mapped[SessionRecord] = relationship(back_populates="turns")


class Artifact(Base):
    __tablename__ = "artifacts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sessions.id"), nullable=False
    )
    artifact_type: Mapped[ArtifactType] = mapped_column(
        Enum(ArtifactType, name="artifact_type", native_enum=True), nullable=False
    )
    storage_uri: Mapped[str] = mapped_column(Text, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    metadata_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )

    session: Mapped[SessionRecord] = relationship(back_populates="artifacts")


class SignalWindow(Base):
    __tablename__ = "signal_windows"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sessions.id"), nullable=False
    )
    topic_key: Mapped[str] = mapped_column(String(100), nullable=False)
    start_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    end_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    source_turn_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)), default=list
    )
    reliability_score: Mapped[float] = mapped_column(Float, nullable=False)

    session: Mapped[SessionRecord] = relationship(back_populates="signal_windows")
    observations: Mapped[list["SignalObservation"]] = relationship(
        back_populates="window"
    )


class SignalObservation(Base):
    __tablename__ = "signal_observations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sessions.id"), nullable=False
    )
    window_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("signal_windows.id")
    )
    modality: Mapped[Modality] = mapped_column(
        Enum(Modality, name="modality_type", native_enum=True), nullable=False
    )
    signal_key: Mapped[str] = mapped_column(String(100), nullable=False)
    value_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    evidence_ref_json: Mapped[dict] = mapped_column(JSONB, default=dict)

    session: Mapped[SessionRecord] = relationship(
        back_populates="signal_observations"
    )
    window: Mapped[SignalWindow | None] = relationship(
        back_populates="observations"
    )


class Hypothesis(Base):
    __tablename__ = "hypotheses"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sessions.id"), nullable=False
    )
    construct_key: Mapped[str] = mapped_column(String(100), nullable=False)
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    score: Mapped[float | None] = mapped_column(Float)
    status: Mapped[HypothesisStatus] = mapped_column(
        Enum(HypothesisStatus, name="hypothesis_status", native_enum=True),
        nullable=False,
    )
    evidence_summary: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_refs_json: Mapped[dict] = mapped_column(JSONB, default=dict)

    session: Mapped[SessionRecord] = relationship(back_populates="hypotheses")


class Profile(Base):
    __tablename__ = "profiles"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sessions.id"), nullable=False
    )
    profile_version: Mapped[str] = mapped_column(String(20), nullable=False)
    student_view_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    counsellor_view_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    school_view_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    red_flags_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )

    session: Mapped[SessionRecord] = relationship(back_populates="profiles")
