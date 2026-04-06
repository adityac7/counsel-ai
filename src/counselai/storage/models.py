"""SQLAlchemy ORM models — SQLite-compatible, async-ready."""
from __future__ import annotations

import enum, json, uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, TypeDecorator,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from counselai.storage.db import Base


class JSONType(TypeDecorator[Any]):
    """Store Python dicts/lists as JSON text in SQLite."""
    impl = Text
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Any) -> str | None:
        if value is None:
            return None
        return json.dumps(value, default=str)

    def process_result_value(self, value: str | None, dialect: Any) -> Any:
        if value is None:
            return None
        return json.loads(value)


class UUIDType(TypeDecorator[uuid.UUID]):
    """Store UUIDs as 36-char strings in SQLite."""
    impl = String(36)
    cache_ok = True

    def process_bind_param(self, value: uuid.UUID | str | None, dialect: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, uuid.UUID):
            return str(value)
        return value

    def process_result_value(self, value: str | None, dialect: Any) -> uuid.UUID | None:
        if value is None:
            return None
        return uuid.UUID(value)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)

def _new_uuid() -> uuid.UUID:
    return uuid.uuid4()

class SessionStatus(str, enum.Enum):
    draft = "draft"
    live = "live"
    uploaded = "uploaded"
    processing = "processing"
    completed = "completed"
    failed = "failed"


class RiskLevel(str, enum.Enum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class Speaker(str, enum.Enum):
    student = "student"
    counsellor = "counsellor"
    system = "system"


class TranscriptSource(str, enum.Enum):
    live_transcript = "live_transcript"
    fallback_transcript = "fallback_transcript"
    manual = "manual"


class HypothesisStatus(str, enum.Enum):
    supported = "supported"
    mixed = "mixed"
    weak = "weak"


class School(Base):
    __tablename__ = "schools"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=_new_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    board: Mapped[str | None] = mapped_column(String(100))
    city: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    students: Mapped[list["Student"]] = relationship(back_populates="school")


class Student(Base):
    __tablename__ = "students"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=_new_uuid)
    external_ref: Mapped[str | None] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    grade: Mapped[str] = mapped_column(String(20), nullable=False)
    section: Mapped[str | None] = mapped_column(String(20))
    school_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType, ForeignKey("schools.id")
    )
    age: Mapped[int | None] = mapped_column(Integer)
    language_pref: Mapped[str | None] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    school: Mapped[School | None] = relationship(back_populates="students")
    sessions: Mapped[list["SessionRecord"]] = relationship(back_populates="student")

    __table_args__ = (
        Index("ix_students_school_id", "school_id"),
        Index("ix_students_external_ref", "external_ref"),
    )


class SessionRecord(Base):
    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=_new_uuid)
    student_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("students.id"), nullable=False
    )
    case_study_id: Mapped[str] = mapped_column(String(100), nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), default=SessionStatus.draft.value, nullable=False
    )
    started_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime)
    duration_seconds: Mapped[int | None] = mapped_column(Integer)
    primary_language: Mapped[str | None] = mapped_column(String(20))
    processing_version: Mapped[str | None] = mapped_column(String(20))

    # New fields — session analysis
    session_summary: Mapped[str | None] = mapped_column(Text)
    risk_level: Mapped[str | None] = mapped_column(String(20))  # RiskLevel enum values
    follow_up_needed: Mapped[bool] = mapped_column(Boolean, default=False)
    topics_discussed: Mapped[dict | None] = mapped_column(JSONType)  # list of strings

    turn_count: Mapped[int | None] = mapped_column(Integer)

    # Full post-session report (JSON blob from report_generator)
    report: Mapped[str | None] = mapped_column(Text)

    # Real-time observations captured via Gemini function calling during session
    observations_json: Mapped[dict | None] = mapped_column(JSONType, default=list)
    segments_json: Mapped[dict | None] = mapped_column(JSONType, default=list)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)

    student: Mapped[Student] = relationship(back_populates="sessions")
    turns: Mapped[list["Turn"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )
    hypotheses: Mapped[list["Hypothesis"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )
    profiles: Mapped[list["Profile"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )
    __table_args__ = (
        Index("ix_sessions_student_id", "student_id"),
        Index("ix_sessions_status", "status"),
        Index("ix_sessions_started_at", "started_at"),
        Index("ix_sessions_risk_level", "risk_level"),
    )


class Turn(Base):
    __tablename__ = "turns"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=_new_uuid)
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("sessions.id"), nullable=False
    )
    turn_index: Mapped[int] = mapped_column(Integer, nullable=False)
    speaker: Mapped[str] = mapped_column(String(20), nullable=False)
    start_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    end_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(30), nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float)

    session: Mapped[SessionRecord] = relationship(back_populates="turns")

    __table_args__ = (
        Index("ix_turns_session_id", "session_id"),
    )


class Hypothesis(Base):
    __tablename__ = "hypotheses"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=_new_uuid)
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("sessions.id"), nullable=False
    )
    construct_key: Mapped[str] = mapped_column(String(100), nullable=False)
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    score: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    evidence_summary: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_refs_json: Mapped[dict | None] = mapped_column(JSONType, default=dict)

    session: Mapped[SessionRecord] = relationship(back_populates="hypotheses")

    __table_args__ = (
        Index("ix_hypotheses_session_id", "session_id"),
    )


class Profile(Base):
    __tablename__ = "profiles"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=_new_uuid)
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("sessions.id"), nullable=False
    )
    profile_version: Mapped[str] = mapped_column(String(20), nullable=False)
    student_view_json: Mapped[dict | None] = mapped_column(JSONType, default=dict)
    counsellor_view_json: Mapped[dict | None] = mapped_column(JSONType, default=dict)
    school_view_json: Mapped[dict | None] = mapped_column(JSONType, default=dict)
    red_flags_json: Mapped[dict | None] = mapped_column(JSONType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    session: Mapped[SessionRecord] = relationship(back_populates="profiles")

    __table_args__ = (
        Index("ix_profiles_session_id", "session_id"),
    )
