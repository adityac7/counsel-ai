"""Counsellor workbench service layer.

Handles session queue, detail review, evidence exploration,
and profile summaries for the counsellor-facing dashboard.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Any, Sequence

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session, joinedload

from counselai.storage.models import (
    Hypothesis,
    HypothesisStatus,
    Profile,
    SessionRecord,
    SessionStatus,
    SignalObservation,
    SignalWindow,
    Student,
    School,
    Turn,
)


# ---------------------------------------------------------------------------
# Data shapes returned by the service layer
# ---------------------------------------------------------------------------


def _enum_val(v):
    """Safely get .value from enum or return string as-is."""
    return v.value if hasattr(v, 'value') else v

class QueueFilters:
    """Parsed filter parameters for the counsellor queue."""

    def __init__(
        self,
        *,
        school_id: str | None = None,
        grade: str | None = None,
        red_flag: bool | None = None,
        status: str | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        search: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ):
        self.school_id = school_id
        self.grade = grade
        self.red_flag = red_flag
        self.status = status
        self.date_from = date_from
        self.date_to = date_to
        self.search = search
        self.limit = min(limit, 200)
        self.offset = max(offset, 0)


# ---------------------------------------------------------------------------
# Service functions
# ---------------------------------------------------------------------------


def get_counsellor_queue(
    db: Session, filters: QueueFilters
) -> dict[str, Any]:
    """Return paginated session list with student info and red flag counts.

    Returns dict with keys: items, total, filters.
    """
    # Base query: sessions joined with student and school
    stmt = (
        select(SessionRecord)
        .join(Student, SessionRecord.student_id == Student.id)
        .outerjoin(School, Student.school_id == School.id)
        .options(
            joinedload(SessionRecord.student).joinedload(Student.school),
            joinedload(SessionRecord.profiles),
        )
    )

    conditions = []

    # Filter by status (default: completed sessions)
    if filters.status:
        try:
            conditions.append(
                SessionRecord.status == SessionStatus(filters.status)
            )
        except ValueError:
            pass
    else:
        conditions.append(
            SessionRecord.status.in_([
                SessionStatus.completed,
                SessionStatus.processing,
            ])
        )

    if filters.school_id:
        try:
            sid = uuid.UUID(filters.school_id)
            conditions.append(Student.school_id == sid)
        except ValueError:
            pass

    if filters.grade:
        conditions.append(Student.grade == filters.grade)

    if filters.date_from:
        conditions.append(
            SessionRecord.started_at >= datetime.combine(
                filters.date_from, datetime.min.time(), tzinfo=timezone.utc
            )
        )

    if filters.date_to:
        conditions.append(
            SessionRecord.started_at <= datetime.combine(
                filters.date_to, datetime.max.time(), tzinfo=timezone.utc
            )
        )

    if filters.search:
        search_term = f"%{filters.search}%"
        conditions.append(Student.full_name.ilike(search_term))

    if conditions:
        stmt = stmt.where(and_(*conditions))

    # Count total before pagination
    count_stmt = select(func.count()).select_from(
        stmt.with_only_columns(SessionRecord.id).subquery()
    )
    total = db.execute(count_stmt).scalar() or 0

    # Order and paginate
    stmt = (
        stmt.order_by(SessionRecord.started_at.desc())
        .offset(filters.offset)
        .limit(filters.limit)
    )

    sessions = db.execute(stmt).unique().scalars().all()

    items = []
    for s in sessions:
        # Count red flags from latest profile
        red_flag_count = 0
        red_flags_data = []
        if s.profiles:
            latest_profile = sorted(s.profiles, key=lambda p: p.created_at, reverse=True)[0]
            rf = latest_profile.red_flags_json
            if isinstance(rf, list):
                red_flag_count = len(rf)
                red_flags_data = rf
            elif isinstance(rf, dict) and rf:
                red_flag_count = 1
                red_flags_data = [rf]

        # Get max severity from red flags
        max_severity = "none"
        for rf in red_flags_data:
            sev = rf.get("severity", "low") if isinstance(rf, dict) else "low"
            if sev == "high":
                max_severity = "high"
                break
            elif sev == "medium" and max_severity != "high":
                max_severity = "medium"
            elif max_severity == "none":
                max_severity = "low"

        items.append({
            "session_id": str(s.id),
            "student_name": s.student.full_name if s.student else "Unknown",
            "student_grade": s.student.grade if s.student else "",
            "school_name": (
                s.student.school.name
                if s.student and s.student.school
                else None
            ),
            "status": _enum_val(s.status),
            "case_study_id": s.case_study_id,
            "started_at": s.started_at.isoformat() if s.started_at else None,
            "ended_at": s.ended_at.isoformat() if s.ended_at else None,
            "duration_seconds": s.duration_seconds,
            "red_flag_count": red_flag_count,
            "max_severity": max_severity,
        })

    # Apply red_flag filter in-memory (simpler than complex subquery)
    if filters.red_flag is True:
        items = [i for i in items if i["red_flag_count"] > 0]
        total = len(items)
    elif filters.red_flag is False:
        items = [i for i in items if i["red_flag_count"] == 0]
        total = len(items)

    return {"items": items, "total": total}


def get_session_review(db: Session, session_id: uuid.UUID) -> dict[str, Any] | None:
    """Full session detail for counsellor review.

    Returns transcript, profile, hypotheses, evidence, and signal data.
    """
    stmt = (
        select(SessionRecord)
        .where(SessionRecord.id == session_id)
        .options(
            joinedload(SessionRecord.student).joinedload(Student.school),
            joinedload(SessionRecord.turns),
            joinedload(SessionRecord.profiles),
            joinedload(SessionRecord.hypotheses),
            joinedload(SessionRecord.signal_windows),
            joinedload(SessionRecord.signal_observations),
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
            "speaker": t.speaker.value,
            "start_ms": t.start_ms,
            "end_ms": t.end_ms,
            "text": t.text,
            "confidence": t.confidence,
        }
        for t in turns
    ]

    # Latest profile
    profile_data = None
    if session.profiles:
        latest = sorted(session.profiles, key=lambda p: p.created_at, reverse=True)[0]
        profile_data = {
            "id": str(latest.id),
            "version": latest.profile_version,
            "counsellor_view": latest.counsellor_view_json or {},
            "student_view": latest.student_view_json or {},
            "school_view": latest.school_view_json or {},
            "red_flags": latest.red_flags_json or [],
            "created_at": latest.created_at.isoformat() if latest.created_at else None,
        }

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

    # Signal windows
    windows_data = [
        {
            "id": str(w.id),
            "topic_key": w.topic_key,
            "start_ms": w.start_ms,
            "end_ms": w.end_ms,
            "reliability_score": w.reliability_score,
            "source_turn_ids": [str(tid) for tid in (w.source_turn_ids or [])],
        }
        for w in sorted(session.signal_windows, key=lambda w: w.start_ms)
    ]

    # Signal observations grouped by modality
    observations_by_modality: dict[str, list[dict]] = {}
    for obs in session.signal_observations:
        mod = obs.modality.value
        if mod not in observations_by_modality:
            observations_by_modality[mod] = []
        observations_by_modality[mod].append({
            "id": str(obs.id),
            "window_id": str(obs.window_id) if obs.window_id else None,
            "signal_key": obs.signal_key,
            "value": obs.value_json or {},
            "confidence": obs.confidence,
            "evidence_ref": obs.evidence_ref_json or {},
        })

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
        "turns": turns_data,
        "profile": profile_data,
        "hypotheses": hypotheses_data,
        "signal_windows": windows_data,
        "observations": observations_by_modality,
    }


def get_session_evidence(
    db: Session, session_id: uuid.UUID
) -> dict[str, Any] | None:
    """Evidence explorer data: observations linked to turns and windows.

    Returns cross-modal evidence graph for drill-down.
    """
    # Get session with all signal data
    stmt = (
        select(SessionRecord)
        .where(SessionRecord.id == session_id)
        .options(
            joinedload(SessionRecord.turns),
            joinedload(SessionRecord.signal_windows).joinedload(
                SignalWindow.observations
            ),
            joinedload(SessionRecord.signal_observations),
            joinedload(SessionRecord.hypotheses),
        )
    )
    session = db.execute(stmt).unique().scalar_one_or_none()
    if session is None:
        return None

    # Build turn lookup
    turn_map = {str(t.id): t for t in session.turns}

    # Build evidence nodes
    evidence_nodes = []
    for obs in session.signal_observations:
        node = {
            "id": str(obs.id),
            "type": "observation",
            "modality": obs.modality.value,
            "signal_key": obs.signal_key,
            "value": obs.value_json or {},
            "confidence": obs.confidence,
            "evidence_ref": obs.evidence_ref_json or {},
        }

        # Link to window
        if obs.window_id:
            window = next(
                (w for w in session.signal_windows if w.id == obs.window_id),
                None,
            )
            if window:
                node["window"] = {
                    "id": str(window.id),
                    "topic_key": window.topic_key,
                    "start_ms": window.start_ms,
                    "end_ms": window.end_ms,
                }
                # Link to turns in this window
                node["related_turns"] = []
                for tid in (window.source_turn_ids or []):
                    t = turn_map.get(str(tid))
                    if t:
                        node["related_turns"].append({
                            "turn_index": t.turn_index,
                            "speaker": t.speaker.value,
                            "text": t.text,
                        })

        evidence_nodes.append(node)

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
        "evidence_nodes": evidence_nodes,
        "hypothesis_links": hypothesis_links,
        "total_observations": len(evidence_nodes),
        "modality_counts": _count_by_key(evidence_nodes, "modality"),
    }


def get_available_schools(db: Session) -> list[dict[str, str]]:
    """List schools for filter dropdowns."""
    stmt = select(School).order_by(School.name)
    schools = db.execute(stmt).scalars().all()
    return [{"id": str(s.id), "name": s.name} for s in schools]


def get_available_grades(db: Session) -> list[str]:
    """List distinct student grades for filter dropdowns."""
    stmt = select(Student.grade).distinct().order_by(Student.grade)
    return [row[0] for row in db.execute(stmt).all()]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _count_by_key(items: list[dict], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        val = item.get(key, "unknown")
        counts[val] = counts.get(val, 0) + 1
    return counts
