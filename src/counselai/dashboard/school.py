"""School-facing analytics service layer.
Aggregate data only — no individual student details exposed.
"""
from __future__ import annotations

import uuid
from collections import Counter
from typing import Any, Sequence

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from counselai.storage.models import (
    Hypothesis, HypothesisStatus, Profile, School,
    SessionRecord, SessionStatus, Student,
)
def _enum_val(v):
    """Safely get .value from enum or return string as-is."""
    return v.value if hasattr(v, 'value') else v
class SchoolAnalyticsService:
    """Aggregate analytics queries scoped to a single school."""

    def __init__(self, db: Session) -> None:
        self.db = db

    # -- School lookup ------------------------------------------------------

    def get_school(self, school_id: uuid.UUID) -> School | None:
        return self.db.get(School, school_id)

    # -- Overview stats -----------------------------------------------------

    def overview(self, school_id: uuid.UUID) -> dict[str, Any]:
        """Return top-level aggregate numbers for a school."""
        school = self.get_school(school_id)
        if school is None:
            return {}

        total_students = (
            self.db.query(func.count(Student.id))
            .filter(Student.school_id == school_id)
            .scalar()
        ) or 0

        total_sessions = (
            self.db.query(func.count(SessionRecord.id))
            .join(Student, SessionRecord.student_id == Student.id)
            .filter(Student.school_id == school_id)
            .scalar()
        ) or 0

        completed_sessions = (
            self.db.query(func.count(SessionRecord.id))
            .join(Student, SessionRecord.student_id == Student.id)
            .filter(
                Student.school_id == school_id,
                SessionRecord.status == SessionStatus.completed,
            )
            .scalar()
        ) or 0

        avg_duration = (
            self.db.query(func.avg(SessionRecord.duration_seconds))
            .join(Student, SessionRecord.student_id == Student.id)
            .filter(
                Student.school_id == school_id,
                SessionRecord.duration_seconds.isnot(None),
            )
            .scalar()
        )

        return {
            "school_id": str(school_id),
            "name": school.name,
            "board": school.board,
            "city": school.city,
            "total_students": total_students,
            "total_sessions": total_sessions,
            "completed_sessions": completed_sessions,
            "avg_duration_seconds": round(avg_duration, 1) if avg_duration else None,
        }

    # -- Grade/section breakdown --------------------------------------------

    def grade_distribution(self, school_id: uuid.UUID) -> list[dict[str, Any]]:
        """Student and session counts grouped by grade."""
        rows = (
            self.db.query(
                Student.grade,
                func.count(func.distinct(Student.id)).label("student_count"),
                func.count(SessionRecord.id).label("session_count"),
            )
            .outerjoin(SessionRecord, SessionRecord.student_id == Student.id)
            .filter(Student.school_id == school_id)
            .group_by(Student.grade)
            .order_by(Student.grade)
            .all()
        )
        return [
            {
                "grade": r.grade,
                "student_count": r.student_count,
                "session_count": r.session_count,
            }
            for r in rows
        ]

    def section_distribution(self, school_id: uuid.UUID) -> list[dict[str, Any]]:
        """Student and session counts grouped by grade + section."""
        rows = (
            self.db.query(
                Student.grade,
                Student.section,
                func.count(func.distinct(Student.id)).label("student_count"),
                func.count(SessionRecord.id).label("session_count"),
            )
            .outerjoin(SessionRecord, SessionRecord.student_id == Student.id)
            .filter(Student.school_id == school_id)
            .group_by(Student.grade, Student.section)
            .order_by(Student.grade, Student.section)
            .all()
        )
        return [
            {
                "grade": r.grade,
                "section": r.section or "—",
                "student_count": r.student_count,
                "session_count": r.session_count,
            }
            for r in rows
        ]

    # -- Red-flag aggregates ------------------------------------------------

    def red_flag_summary(self, school_id: uuid.UUID) -> dict[str, Any]:
        """Aggregate red-flag counts by severity across all profiles.

        Reads ``red_flags_json`` from Profile records.  Does NOT expose
        which student triggered which flag — only totals and per-key counts.
        """
        profiles = (
            self.db.query(Profile.red_flags_json)
            .join(SessionRecord, Profile.session_id == SessionRecord.id)
            .join(Student, SessionRecord.student_id == Student.id)
            .filter(Student.school_id == school_id)
            .all()
        )

        severity_counts: Counter[str] = Counter()
        flag_key_counts: Counter[str] = Counter()
        total_flags = 0

        for (flags_json,) in profiles:
            if flags_json is None:
                continue
            flags = flags_json if isinstance(flags_json, list) else flags_json.get("flags", [])
            for flag in flags:
                if not isinstance(flag, dict):
                    continue
                sev = flag.get("severity", "unknown")
                key = flag.get("key", "unknown")
                severity_counts[sev] += 1
                flag_key_counts[key] += 1
                total_flags += 1

        return {
            "total_flags": total_flags,
            "by_severity": dict(severity_counts),
            "by_key": dict(flag_key_counts.most_common(15)),
        }

    # -- Topic clusters -----------------------------------------------------

    def topic_clusters(self, school_id: uuid.UUID) -> list[dict[str, Any]]:
        """Aggregate school themes from Profile JSON (school_view.themes)."""
        rows = (
            self.db.query(Profile.school_view_json)
            .join(SessionRecord, Profile.session_id == SessionRecord.id)
            .join(Student, SessionRecord.student_id == Student.id)
            .filter(Student.school_id == school_id)
            .all()
        )
        counts: Counter[str] = Counter()
        for (school_view,) in rows:
            themes = school_view.get("themes", []) if isinstance(school_view, dict) else []
            for theme in themes:
                text = str(theme or "").strip()
                if text:
                    counts[text] += 1
        return [
            {"topic_key": key, "occurrences": count, "avg_reliability": None}
            for key, count in counts.most_common(20)
        ]

    # -- Hypothesis / construct distribution --------------------------------

    def construct_distribution(self, school_id: uuid.UUID) -> list[dict[str, Any]]:
        """Aggregate hypothesis statuses across sessions for the school."""
        rows = (
            self.db.query(
                Hypothesis.construct_key,
                Hypothesis.label,
                func.count(Hypothesis.id).label("total"),
                func.count(
                    case(
                        (Hypothesis.status == HypothesisStatus.supported, 1),
                    )
                ).label("supported"),
                func.count(
                    case(
                        (Hypothesis.status == HypothesisStatus.mixed, 1),
                    )
                ).label("mixed"),
                func.count(
                    case(
                        (Hypothesis.status == HypothesisStatus.weak, 1),
                    )
                ).label("weak"),
                func.avg(Hypothesis.score).label("avg_score"),
            )
            .join(SessionRecord, Hypothesis.session_id == SessionRecord.id)
            .join(Student, SessionRecord.student_id == Student.id)
            .filter(Student.school_id == school_id)
            .group_by(Hypothesis.construct_key, Hypothesis.label)
            .order_by(func.count(Hypothesis.id).desc())
            .limit(20)
            .all()
        )
        if rows:
            return [
                {
                    "construct_key": r.construct_key,
                    "label": r.label,
                    "total": r.total,
                    "supported": r.supported,
                    "mixed": r.mixed,
                    "weak": r.weak,
                    "avg_score": round(float(r.avg_score), 3) if r.avg_score else None,
                }
                for r in rows
            ]
        return self._profile_construct_distribution(school_id)

    def _profile_construct_distribution(
        self, school_id: uuid.UUID
    ) -> list[dict[str, Any]]:
        """Fallback: aggregate constructs from counsellor profile views."""
        rows = (
            self.db.query(Profile.counsellor_view_json)
            .join(SessionRecord, Profile.session_id == SessionRecord.id)
            .join(Student, SessionRecord.student_id == Student.id)
            .filter(Student.school_id == school_id)
            .all()
        )
        totals: dict[str, dict[str, Any]] = {}
        for (view_json,) in rows:
            constructs = view_json.get("constructs", []) if isinstance(view_json, dict) else []
            for construct in constructs:
                if not isinstance(construct, dict):
                    continue
                construct_key = str(construct.get("key") or "").strip()
                label = str(construct.get("label") or "").strip()
                if not construct_key or not label:
                    continue
                bucket = totals.setdefault(
                    construct_key,
                    {"construct_key": construct_key, "label": label, "total": 0,
                     "supported": 0, "mixed": 0, "weak": 0, "score_sum": 0.0, "score_count": 0},
                )
                bucket["total"] += 1
                status = str(construct.get("status") or "mixed").lower()
                if status in ("supported", "mixed", "weak"):
                    bucket[status] += 1
                score = construct.get("score")
                if isinstance(score, (int, float)):
                    bucket["score_sum"] += float(score)
                    bucket["score_count"] += 1
        results: list[dict[str, Any]] = []
        for bucket in totals.values():
            score_count = bucket.pop("score_count")
            score_sum = bucket.pop("score_sum")
            bucket["avg_score"] = round(score_sum / score_count, 3) if score_count else None
            results.append(bucket)
        return sorted(results, key=lambda item: item["total"], reverse=True)[:20]

    # -- Trend lines (sessions over time) -----------------------------------

    def session_trend(
        self,
        school_id: uuid.UUID,
        *,
        granularity: str = "month",
    ) -> list[dict[str, Any]]:
        """Session counts over time, bucketed by month or week."""
        # SQLite-compatible date bucketing (no date_trunc)
        if granularity == "week":
            bucket = func.strftime("%Y-%W", SessionRecord.started_at)
        else:
            bucket = func.strftime("%Y-%m", SessionRecord.started_at)
        rows = (
            self.db.query(
                bucket.label("period"),
                func.count(SessionRecord.id).label("session_count"),
                func.count(func.distinct(Student.id)).label("unique_students"),
            )
            .join(Student, SessionRecord.student_id == Student.id)
            .filter(Student.school_id == school_id)
            .group_by(bucket)
            .order_by(bucket)
            .all()
        )
        return [
            {
                "period": (
                    r.period.isoformat()
                    if hasattr(r.period, "isoformat")
                    else str(r.period)
                ) if r.period else None,
                "session_count": r.session_count,
                "unique_students": r.unique_students,
            }
            for r in rows
        ]

    # -- Class-level insights -----------------------------------------------

    def class_insights(
        self, school_id: uuid.UUID, grade: str
    ) -> dict[str, Any]:
        """Aggregate insights for a specific grade within the school."""
        base = (
            self.db.query(Student.id)
            .filter(Student.school_id == school_id, Student.grade == grade)
            .subquery()
        )

        student_count = self.db.query(func.count()).select_from(base).scalar() or 0

        session_count = (
            self.db.query(func.count(SessionRecord.id))
            .filter(SessionRecord.student_id.in_(self.db.query(base.c.id)))
            .scalar()
        ) or 0

        completed = (
            self.db.query(func.count(SessionRecord.id))
            .filter(
                SessionRecord.student_id.in_(self.db.query(base.c.id)),
                SessionRecord.status == SessionStatus.completed,
            )
            .scalar()
        ) or 0

        # Red-flag count for this grade
        red_flag_total = 0
        profiles = (
            self.db.query(Profile.red_flags_json)
            .join(SessionRecord, Profile.session_id == SessionRecord.id)
            .filter(SessionRecord.student_id.in_(self.db.query(base.c.id)))
            .all()
        )
        for (flags_json,) in profiles:
            if flags_json is None:
                continue
            flags = flags_json if isinstance(flags_json, list) else flags_json.get("flags", [])
            red_flag_total += len(flags)

        return {
            "grade": grade,
            "student_count": student_count,
            "session_count": session_count,
            "completed_sessions": completed,
            "red_flag_total": red_flag_total,
            "top_topics": [],
        }

    # -- Batch analysis summary ---------------------------------------------

    def batch_summary(self, school_id: uuid.UUID) -> dict[str, Any]:
        """High-level batch analysis stats: processing pipeline health."""
        status_counts = (
            self.db.query(
                SessionRecord.status,
                func.count(SessionRecord.id).label("cnt"),
            )
            .join(Student, SessionRecord.student_id == Student.id)
            .filter(Student.school_id == school_id)
            .group_by(SessionRecord.status)
            .all()
        )
        return {
            "by_status": {str(_enum_val(r.status)): r.cnt for r in status_counts},
        }

    # -- Full analytics payload ---------------------------------------------

    def full_analytics(
        self,
        school_id: uuid.UUID,
        *,
        grade: str | None = None,
        trend_granularity: str = "month",
    ) -> dict[str, Any]:
        """Assemble the complete school analytics response."""
        data = self.overview(school_id)
        if not data:
            return {}

        data["grade_distribution"] = self.grade_distribution(school_id)
        data["section_distribution"] = self.section_distribution(school_id)
        data["red_flag_summary"] = self.red_flag_summary(school_id)
        data["topic_clusters"] = self.topic_clusters(school_id)
        data["construct_distribution"] = self.construct_distribution(school_id)
        data["session_trend"] = self.session_trend(
            school_id, granularity=trend_granularity
        )
        data["batch_summary"] = self.batch_summary(school_id)

        if grade:
            data["class_insights"] = self.class_insights(school_id, grade)

        return data
