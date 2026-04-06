"""Counsellor dashboard service layer.

Handles the paginated session queue, filter options, detailed session
review, and evidence exploration for the counsellor-facing dashboard.

Merged from counsellor_queue.py + counsellor_review.py.
"""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session, joinedload

from counselai.storage.models import (
    School,
    SessionRecord,
    SessionStatus,
    Student,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _enum_val(v):
    """Safely get .value from enum or return string as-is."""
    return v.value if hasattr(v, "value") else v


def _count_by_key(items: list[dict], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        val = item.get(key, "unknown")
        counts[val] = counts.get(val, 0) + 1
    return counts


def normalize_profile_for_dashboard(profile: dict | None) -> dict | None:
    """Normalize a profile dict for counsellor dashboard rendering.

    Handles both the legacy profile_generator format and the new
    unified_analyzer format. Returns the profile as-is if already normalized.
    """
    if not isinstance(profile, dict) or not profile:
        return None
    if "counsellor_view" in profile or "constructs" in profile:
        return profile
    return profile


# ---------------------------------------------------------------------------
# Data shapes
# ---------------------------------------------------------------------------


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
# Queue service functions
# ---------------------------------------------------------------------------


def get_counsellor_queue(
    db: Session, filters: QueueFilters
) -> dict[str, Any]:
    """Return paginated session list with student info and red flag counts."""
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

    count_stmt = select(func.count()).select_from(
        stmt.with_only_columns(SessionRecord.id).subquery()
    )
    total = db.execute(count_stmt).scalar() or 0

    stmt = (
        stmt.order_by(SessionRecord.started_at.desc())
        .offset(filters.offset)
        .limit(filters.limit)
    )

    sessions = db.execute(stmt).unique().scalars().all()

    items = []
    for s in sessions:
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
        elif s.report:
            try:
                report = json.loads(s.report) if isinstance(s.report, str) else s.report
                profile = report.get("profile", {}) if isinstance(report, dict) else {}
                rf = profile.get("red_flags", [])
                if isinstance(rf, list):
                    red_flag_count = len(rf)
                    red_flags_data = rf
            except (ValueError, TypeError, AttributeError):
                pass

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

        student = s.student
        school = student.school if student else None
        items.append({
            "session_id": str(s.id),
            "student_name": student.full_name if student else "Unknown",
            "student_grade": student.grade if student else "",
            "student_section": student.section if student else None,
            "school_name": school.name if school else None,
            "school_id": str(school.id) if school else None,
            "student_id": str(student.id) if student else None,
            "status": _enum_val(s.status),
            "case_study_id": s.case_study_id,
            "started_at": s.started_at.isoformat() if s.started_at else None,
            "ended_at": s.ended_at.isoformat() if s.ended_at else None,
            "duration_seconds": s.duration_seconds,
            "red_flag_count": red_flag_count,
            "max_severity": max_severity,
        })

    if filters.red_flag is True:
        items = [i for i in items if i["red_flag_count"] > 0]
        total = len(items)
    elif filters.red_flag is False:
        items = [i for i in items if i["red_flag_count"] == 0]
        total = len(items)

    return {"items": items, "total": total}


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
# Review service functions
# ---------------------------------------------------------------------------


def get_session_review(db: Session, session_id: uuid.UUID) -> dict[str, Any] | None:
    """Full session detail for counsellor review."""
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
        try:
            report = json.loads(session.report) if isinstance(session.report, str) else session.report
            candidate = report.get("profile")
            if not candidate:
                candidate = report.get("profile_raw", {})
            profile_data = normalize_profile_for_dashboard(candidate)
        except (ValueError, TypeError, AttributeError):
            pass

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

    segments = session.segments_json or []
    signal_windows = segments if isinstance(segments, list) else []

    obs_raw = session.observations_json or []
    obs_by_modality: dict[str, list[dict]] = {}
    if isinstance(obs_raw, list):
        for obs in obs_raw:
            mod = obs.get("modality", "unknown")
            obs_by_modality.setdefault(mod, []).append({
                "signal_key": obs.get("signal", ""),
                "confidence": obs.get("confidence", 0),
                "value": {"detail": obs.get("detail", "")},
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
            "session_summary": session.session_summary,
            "risk_level": _enum_val(session.risk_level) if session.risk_level else None,
            "follow_up_needed": session.follow_up_needed,
        },
        "student": student_info,
        "transcript": turns_data,
        "turns": turns_data,
        "profile": profile_data,
        "duration_seconds": session.duration_seconds,
        "hypotheses": hypotheses_data,
        "signal_windows": signal_windows,
        "observations": obs_by_modality,
    }


def get_session_evidence(
    db: Session, session_id: uuid.UUID
) -> dict[str, Any] | None:
    """Evidence explorer data."""
    stmt = (
        select(SessionRecord)
        .where(SessionRecord.id == session_id)
        .options(
            joinedload(SessionRecord.hypotheses),
            joinedload(SessionRecord.profiles),
        )
    )
    session = db.execute(stmt).unique().scalar_one_or_none()
    if session is None:
        return None

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

    obs_raw = session.observations_json or []
    observations = obs_raw if isinstance(obs_raw, list) else []

    seg_raw = session.segments_json or []
    segments = seg_raw if isinstance(seg_raw, list) else []

    red_flags: list = []
    if session.profiles:
        latest = sorted(session.profiles, key=lambda p: p.created_at, reverse=True)[0]
        rf = latest.red_flags_json
        if isinstance(rf, list):
            red_flags = rf
        elif isinstance(rf, dict) and rf:
            red_flags = [rf]

    evidence_nodes = []
    for obs in observations:
        evidence_nodes.append({
            "modality": obs.get("modality", "unknown"),
            "signal_key": obs.get("signal", ""),
            "confidence": obs.get("confidence", 0),
            "value": {"detail": obs.get("detail", "")},
        })

    modality_counts: dict[str, int] = {}
    for obs in observations:
        mod = obs.get("modality", "unknown")
        modality_counts[mod] = modality_counts.get(mod, 0) + 1

    return {
        "session_id": str(session_id),
        "hypotheses": hypothesis_links,
        "hypothesis_links": hypothesis_links,
        "observations": observations,
        "segments": segments,
        "red_flags": red_flags,
        "evidence_nodes": evidence_nodes,
        "total_observations": len(observations),
        "modality_counts": modality_counts,
    }
