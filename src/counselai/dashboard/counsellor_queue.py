"""Counsellor queue service layer.

Handles the paginated session queue, filter options,
and supporting helpers for the counsellor-facing dashboard.
"""

from __future__ import annotations

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
        # Count red flags from latest profile or session.report
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
            # Fall back to session.report JSON
            try:
                import json as _json
                report = _json.loads(s.report) if isinstance(s.report, str) else s.report
                profile = report.get("profile", {}) if isinstance(report, dict) else {}
                rf = profile.get("red_flags", [])
                if isinstance(rf, list):
                    red_flag_count = len(rf)
                    red_flags_data = rf
            except (ValueError, TypeError, AttributeError):
                pass

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

    # Apply red_flag filter in-memory (simpler than complex subquery)
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
