"""Counsellor session review service layer.

Handles detailed session review and evidence exploration
for the counsellor-facing dashboard.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

def normalize_profile_for_dashboard(profile: dict | None) -> dict | None:
    """Normalize a profile dict for counsellor dashboard rendering.

    Handles both the legacy profile_generator format and the new
    unified_analyzer format. Returns the profile as-is if already normalized.
    """
    if not isinstance(profile, dict) or not profile:
        return None
    # Already normalized (has counsellor_view) or is unified format (has constructs)
    if "counsellor_view" in profile or "constructs" in profile:
        return profile
    # Legacy format: reshape minimally
    return profile
from counselai.storage.models import (
    SessionRecord,
    Student,
)

from counselai.dashboard.counsellor_queue import _count_by_key, _enum_val


# ---------------------------------------------------------------------------
# Service functions
# ---------------------------------------------------------------------------


def get_session_review(db: Session, session_id: uuid.UUID) -> dict[str, Any] | None:
    """Full session detail for counsellor review.

    Returns transcript, profile, hypotheses, and evidence data.
    """
    stmt = (
        select(SessionRecord)
        .where(SessionRecord.id == session_id)
        .options(
            joinedload(SessionRecord.student).joinedload(Student.school),
            joinedload(SessionRecord.turns),
            joinedload(SessionRecord.profiles),
            joinedload(SessionRecord.hypotheses),
        )
    )
    session = db.execute(stmt).unique().scalar_one_or_none()
    if session is None:
        return None

    # Student info
    student_info = {}
    if session.student:
        student_info = {
            "id": str(session.student.id),
            "name": session.student.full_name,
            "grade": session.student.grade,
            "section": session.student.section,
            "age": session.student.age,
            "school": (
                session.student.school.name if session.student.school else None
            ),
        }

    # Turns (sorted)
    turns = sorted(session.turns, key=lambda t: t.turn_index)
    turns_data = [
        {
            "id": str(t.id),
            "turn_index": t.turn_index,
            "speaker": _enum_val(t.speaker),
            "role": _enum_val(t.speaker),
            "text": t.text,
            "confidence": t.confidence,
            "start_ms": t.start_ms,
            "end_ms": t.end_ms,
        }
        for t in turns
    ]

    # Latest profile — check Profile model first, then fall back to session.report JSON
    profile_data = None
    if session.profiles:
        latest = sorted(session.profiles, key=lambda p: p.created_at, reverse=True)[0]
        profile_data = normalize_profile_for_dashboard({
            "id": str(latest.id),
            "version": latest.profile_version,
            "counsellor_view": latest.counsellor_view_json or {},
            "student_view": latest.student_view_json or {},
            "school_view": latest.school_view_json or {},
            "red_flags": latest.red_flags_json or [],
            "created_at": latest.created_at.isoformat() if latest.created_at else None,
        })
    elif session.report:
        # Fall back to the report JSON saved by analyze-session endpoint
        try:
            import json as _json
            report = _json.loads(session.report) if isinstance(session.report, str) else session.report
            candidate = report.get("profile")
            if not candidate:
                candidate = report.get("profile_raw", {})
            profile_data = normalize_profile_for_dashboard(candidate)
        except (ValueError, TypeError, AttributeError):
            pass

    # Hypotheses
    hypotheses_data = [
        {
            "id": str(h.id),
            "construct_key": h.construct_key,
            "label": h.label,
            "score": h.score,
            "status": _enum_val(h.status),
            "evidence_summary": h.evidence_summary,
            "evidence_refs": h.evidence_refs_json or {},
        }
        for h in sorted(session.hypotheses, key=lambda h: h.construct_key)
    ]

    return {
        "session": {
            "id": str(session.id),
            "status": _enum_val(session.status),
            "case_study_id": session.case_study_id,
            "provider": session.provider,
            "started_at": session.started_at.isoformat() if session.started_at else None,
            "ended_at": session.ended_at.isoformat() if session.ended_at else None,
            "duration_seconds": session.duration_seconds,
            "primary_language": session.primary_language,
            "processing_version": session.processing_version,
        },
        "student": student_info,
        "transcript": turns_data,
        "turns": turns_data,
        "profile": profile_data,
        "duration_seconds": session.duration_seconds,
        "hypotheses": hypotheses_data,
        "signal_windows": [],
        "observations": {},
    }


def get_session_evidence(
    db: Session, session_id: uuid.UUID
) -> dict[str, Any] | None:
    """Evidence explorer data.

    Signal tables no longer exist; return hypothesis links only.
    """
    stmt = (
        select(SessionRecord)
        .where(SessionRecord.id == session_id)
        .options(
            joinedload(SessionRecord.hypotheses),
        )
    )
    session = db.execute(stmt).unique().scalar_one_or_none()
    if session is None:
        return None

    # Build hypothesis links
    hypothesis_links = []
    for h in session.hypotheses:
        hypothesis_links.append({
            "hypothesis_id": str(h.id),
            "construct_key": h.construct_key,
            "label": h.label,
            "status": _enum_val(h.status),
            "score": h.score,
            "evidence_summary": h.evidence_summary,
            "evidence_refs": h.evidence_refs_json or {},
        })

    return {
        "session_id": str(session_id),
        "evidence_nodes": [],
        "hypothesis_links": hypothesis_links,
        "total_observations": 0,
        "modality_counts": {},
    }
