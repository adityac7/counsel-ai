"""Helpers for live session persistence.

These helpers keep websocket routes focused on transport logic instead of
embedding ad-hoc student/session creation and teardown writes inline.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from counselai.storage.models import School, SessionRecord, SessionStatus, Student, TranscriptSource, Turn


@dataclass(slots=True)
class LiveSessionHandle:
    """Identifiers returned when a live session row is created."""

    session_id: str
    started_at: datetime


def _as_utc(dt: datetime | None) -> datetime | None:
    """Normalize naive/aware datetimes into UTC for safe comparisons."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


async def _get_or_create_school(
    db: AsyncSession,
    *,
    school_name: str,
) -> School | None:
    clean_name = school_name.strip()
    if not clean_name:
        return None

    stmt = select(School).where(School.name == clean_name)
    result = await db.execute(stmt)
    school = result.scalar_one_or_none()
    if school is not None:
        return school

    school = School(name=clean_name)
    db.add(school)
    await db.flush()
    return school


async def _get_or_create_student(
    db: AsyncSession,
    *,
    student_name: str,
    student_grade: str,
    student_section: str,
    student_age: int,
    school_name: str,
    language: str | None = None,
) -> Student:
    school = await _get_or_create_school(db, school_name=school_name)

    # Match on all identifying fields to avoid collisions (e.g. two "Priya"s
    # at different schools or in different grades).
    stmt = select(Student).where(
        Student.full_name == student_name,
        Student.grade == student_grade,
        Student.section == (student_section or None),
        Student.school_id == (school.id if school else None),
    )
    result = await db.execute(stmt)
    student = result.scalar_one_or_none()

    if student is None:
        student = Student(
            id=uuid.uuid4(),
            full_name=student_name,
            grade=student_grade,
            section=student_section or None,
            age=student_age,
            school_id=school.id if school else None,
            language_pref=language or None,
        )
        db.add(student)
        await db.flush()
        return student

    # Keep the existing student row aligned with the latest session metadata.
    student.age = student_age or student.age
    if language:
        student.language_pref = language
    await db.flush()
    return student


async def create_live_session(
    db: AsyncSession,
    *,
    student_name: str,
    student_grade: str,
    student_section: str,
    school_name: str,
    student_age: int,
    scenario: str,
    case_study_id: str | None = None,
    language: str = "hinglish",
) -> LiveSessionHandle:
    """Create the live session row as soon as the websocket session starts."""
    student = await _get_or_create_student(
        db,
        student_name=student_name,
        student_grade=student_grade,
        student_section=student_section,
        student_age=student_age,
        school_name=school_name,
        language=language,
    )

    started_at = datetime.now(timezone.utc)
    session_rec = SessionRecord(
        id=uuid.uuid4(),
        student_id=student.id,
        case_study_id=case_study_id or (scenario[:100] if scenario else "general"),
        provider="gemini-live",
        status=SessionStatus.live.value,
        started_at=started_at,
        primary_language=language,
        turn_count=0,
    )
    db.add(session_rec)
    await db.commit()
    return LiveSessionHandle(session_id=str(session_rec.id), started_at=started_at)


async def finalize_live_session(
    db: AsyncSession,
    *,
    session_id: str,
    turns: list[dict],
    observations: list[dict] | None = None,
    segments: list[dict] | None = None,
    status: SessionStatus = SessionStatus.completed,
    ended_at: datetime | None = None,
) -> str | None:
    """Finalize a live session row with transcript turns, observations, and timing."""
    session_uuid = uuid.UUID(session_id)
    session = await db.get(SessionRecord, session_uuid)
    if session is None:
        return None

    final_ended_at = _as_utc(ended_at or datetime.now(timezone.utc))
    started_at = _as_utc(session.started_at)
    if started_at and final_ended_at and final_ended_at < started_at:
        final_ended_at = started_at

    session.status = status.value
    session.ended_at = final_ended_at
    if started_at and final_ended_at:
        session.duration_seconds = max(
            0, int((final_ended_at - started_at).total_seconds())
        )
    session.turn_count = len(turns)
    session.observations_json = list(observations) if observations else []
    session.segments_json = list(segments) if segments else []

    await db.execute(delete(Turn).where(Turn.session_id == session_uuid))
    for i, turn in enumerate(turns):
        db.add(
            Turn(
                id=uuid.uuid4(),
                session_id=session_uuid,
                turn_index=i,
                speaker=turn["role"],
                start_ms=turn.get("start_ms", 0),
                end_ms=turn.get("end_ms", 0),
                text=turn["text"],
                source=TranscriptSource.live_transcript.value,
            )
        )

    await db.commit()
    return str(session.id)
