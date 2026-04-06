"""Student dashboard service layer.

Fetches student info, session history, and profile data for the
student-facing insights page. All language is encouraging and
non-clinical — no red flags, no risk scores, no diagnostic labels.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from counselai.storage.models import (
    Profile,
    SessionRecord,
    SessionStatus,
    Student,
)


def get_student(db: Session, student_id: uuid.UUID) -> Student | None:
    """Fetch a student by ID."""
    return db.get(Student, student_id)


def get_student_sessions(
    db: Session, student_id: uuid.UUID, *, limit: int = 50
) -> list[SessionRecord]:
    """Return completed sessions for a student, newest first.

    Eagerly loads profiles to avoid N+1 queries in callers.
    """
    stmt = (
        select(SessionRecord)
        .where(
            SessionRecord.student_id == student_id,
            SessionRecord.status == SessionStatus.completed,
        )
        .options(joinedload(SessionRecord.profiles))
        .order_by(SessionRecord.started_at.desc())
        .limit(limit)
    )
    return list(db.execute(stmt).unique().scalars().all())


def _empty_student_view() -> dict[str, Any]:
    """Return a blank student-safe view dict."""
    return {
        "strengths": [],
        "interests": [],
        "growth_areas": [],
        "next_steps": [],
        "summary": "",
        "encouragement": "",
    }


def get_student_view(
    profile: Profile | None,
    *,
    session: SessionRecord | None = None,
) -> dict[str, Any]:
    """Extract the student-safe view from a profile record.

    Returns a dict with: strengths, interests, growth_areas,
    next_steps, summary, encouragement.
    Never includes red flags, risk scores, or clinical language.

    If *profile* has no ``student_view_json`` but *session* carries a
    ``session_summary``, a minimal view is built from the summary so the
    dashboard is not blank.
    """
    if profile is None and session is None:
        return _empty_student_view()

    view = (profile.student_view_json or {}) if profile else {}

    # If the view is empty but we have a session summary, build a minimal view
    if not view and session and session.session_summary:
        return {
            **_empty_student_view(),
            "summary": session.session_summary,
        }

    return {
        "strengths": view.get("strengths", []),
        "interests": view.get("interests", []),
        "growth_areas": view.get("growth_areas", []),
        # Canonical key is "next_steps"; fall back to legacy "suggested_next_steps"
        "next_steps": view.get("next_steps") or view.get("suggested_next_steps", []),
        "summary": view.get("summary", ""),
        "encouragement": view.get("encouragement", ""),
    }


def _latest_profile_from_session(session: SessionRecord) -> Profile | None:
    """Get the latest profile from an eagerly-loaded session.profiles list."""
    if not session.profiles:
        return None
    return sorted(session.profiles, key=lambda p: p.created_at, reverse=True)[0]


def build_growth_snapshots(
    sessions: list[SessionRecord],
) -> list[dict[str, Any]]:
    """Build growth snapshots from historical sessions.

    Each snapshot contains the session date, case study topic,
    and a condensed student-safe summary. Shows how the student
    has grown across sessions.
    """
    snapshots = []

    for session in sessions:
        profile = _latest_profile_from_session(session)
        view = get_student_view(profile, session=session)

        snapshots.append({
            "session_id": str(session.id),
            "date": session.started_at.isoformat() if session.started_at else "",
            "case_study_id": session.case_study_id,
            "duration_seconds": session.duration_seconds,
            "strengths": view["strengths"],
            "interests": view["interests"],
            "growth_areas": view["growth_areas"],
            "summary": view["summary"],
        })

    return snapshots


def build_student_dashboard(
    db: Session, student_id: uuid.UUID
) -> dict[str, Any]:
    """Assemble the full student dashboard payload.

    Returns everything the student insights page needs:
    - Student info (name, grade)
    - Latest session profile (strengths, interests, growth, next steps)
    - Historical growth snapshots
    - Aggregate stats (total sessions, topics explored)
    """
    student = get_student(db, student_id)
    if student is None:
        return None

    sessions = get_student_sessions(db, student_id)
    latest_profile = None
    latest_view = _empty_student_view()

    if sessions:
        latest_profile = _latest_profile_from_session(sessions[0])
        latest_view = get_student_view(latest_profile, session=sessions[0])

    snapshots = build_growth_snapshots(sessions[:10])

    # Aggregate unique topics explored
    topics = list({s.case_study_id for s in sessions})

    # Collect all unique strengths and interests across sessions
    all_strengths: list[str] = []
    all_interests: list[str] = []
    seen_strengths: set[str] = set()
    seen_interests: set[str] = set()

    for snap in snapshots:
        for s in snap["strengths"]:
            if s.lower() not in seen_strengths:
                seen_strengths.add(s.lower())
                all_strengths.append(s)
        for i in snap["interests"]:
            if i.lower() not in seen_interests:
                seen_interests.add(i.lower())
                all_interests.append(i)

    return {
        "student": {
            "id": str(student.id),
            "full_name": student.full_name,
            "grade": student.grade,
            "section": student.section or "",
        },
        "stats": {
            "total_sessions": len(sessions),
            "topics_explored": topics,
        },
        "latest": latest_view,
        "growth_snapshots": snapshots,
        "all_strengths": all_strengths[:12],
        "all_interests": all_interests[:12],
    }
