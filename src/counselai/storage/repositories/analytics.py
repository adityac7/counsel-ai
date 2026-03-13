"""Async analytics repository — aggregate queries for dashboard."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import case, cast, Float, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from counselai.storage.models import (
    SessionFeedback,
    SessionRecord,
    Student,
    Turn,
)


class AnalyticsRepository:
    """Read-only aggregate queries for the dashboard."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def session_counts_by_status(self) -> dict[str, int]:
        """Count sessions grouped by status."""
        stmt = (
            select(SessionRecord.status, func.count(SessionRecord.id))
            .group_by(SessionRecord.status)
        )
        result = await self.db.execute(stmt)
        return {row[0]: row[1] for row in result.all()}

    async def session_counts_by_risk(self) -> dict[str, int]:
        """Count sessions grouped by risk_level (excludes NULL)."""
        stmt = (
            select(SessionRecord.risk_level, func.count(SessionRecord.id))
            .where(SessionRecord.risk_level.isnot(None))
            .group_by(SessionRecord.risk_level)
        )
        result = await self.db.execute(stmt)
        return {row[0]: row[1] for row in result.all()}

    async def sessions_per_day(
        self,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """Sessions per day within a date range. Returns [{date, count}, ...]."""
        # SQLite date function
        day_col = func.date(SessionRecord.started_at)
        stmt = select(day_col.label("day"), func.count(SessionRecord.id).label("count"))

        if since is not None:
            stmt = stmt.where(SessionRecord.started_at >= since)
        if until is not None:
            stmt = stmt.where(SessionRecord.started_at <= until)

        stmt = stmt.group_by(day_col).order_by(day_col)
        result = await self.db.execute(stmt)
        return [{"date": row.day, "count": row.count} for row in result.all()]

    async def average_session_duration(self) -> float | None:
        """Average duration in seconds across completed sessions."""
        stmt = select(func.avg(SessionRecord.duration_seconds)).where(
            SessionRecord.status == "completed",
            SessionRecord.duration_seconds.isnot(None),
        )
        result = await self.db.execute(stmt)
        return result.scalar()

    async def average_turn_count(self) -> float | None:
        """Average turn count across sessions that have it set."""
        stmt = select(func.avg(SessionRecord.turn_count)).where(
            SessionRecord.turn_count.isnot(None)
        )
        result = await self.db.execute(stmt)
        return result.scalar()

    async def follow_up_stats(self) -> dict[str, int]:
        """Count sessions needing vs not needing follow-up."""
        stmt = select(
            func.sum(case((SessionRecord.follow_up_needed == True, 1), else_=0)).label("needed"),  # noqa: E712
            func.sum(case((SessionRecord.follow_up_needed == False, 1), else_=0)).label("not_needed"),  # noqa: E712
        )
        result = await self.db.execute(stmt)
        row = result.one()
        return {"follow_up_needed": row.needed or 0, "no_follow_up": row.not_needed or 0}

    async def top_topics(self, *, limit: int = 10) -> list[dict[str, Any]]:
        """Most common topics across all sessions (from topics_discussed JSON).

        Because SQLite doesn't have native JSON array unnest, we pull
        sessions with topics and aggregate in Python.
        """
        stmt = select(SessionRecord.topics_discussed).where(
            SessionRecord.topics_discussed.isnot(None)
        )
        result = await self.db.execute(stmt)

        topic_counts: dict[str, int] = {}
        for (topics_json,) in result.all():
            if isinstance(topics_json, list):
                for topic in topics_json:
                    if isinstance(topic, str):
                        topic_counts[topic] = topic_counts.get(topic, 0) + 1

        sorted_topics = sorted(topic_counts.items(), key=lambda x: x[1], reverse=True)
        return [{"topic": t, "count": c} for t, c in sorted_topics[:limit]]

    async def feedback_summary(self) -> dict[str, Any]:
        """Aggregate feedback stats: avg rating, helpful %, total responses."""
        stmt = select(
            func.count(SessionFeedback.id).label("total"),
            func.avg(cast(SessionFeedback.rating, Float)).label("avg_rating"),
            func.sum(case((SessionFeedback.helpful == True, 1), else_=0)).label("helpful_count"),  # noqa: E712
        )
        result = await self.db.execute(stmt)
        row = result.one()
        total = row.total or 0
        return {
            "total_responses": total,
            "average_rating": round(row.avg_rating, 2) if row.avg_rating else None,
            "helpful_pct": round((row.helpful_count or 0) / total * 100, 1) if total > 0 else None,
        }

    async def students_with_most_sessions(self, *, limit: int = 10) -> list[dict[str, Any]]:
        """Top students by session count."""
        stmt = (
            select(
                Student.id,
                Student.full_name,
                Student.grade,
                func.count(SessionRecord.id).label("session_count"),
            )
            .join(SessionRecord, SessionRecord.student_id == Student.id)
            .group_by(Student.id, Student.full_name, Student.grade)
            .order_by(func.count(SessionRecord.id).desc())
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        return [
            {
                "student_id": str(row.id),
                "name": row.full_name,
                "grade": row.grade,
                "session_count": row.session_count,
            }
            for row in result.all()
        ]

    async def mood_shift_distribution(self) -> list[dict[str, Any]]:
        """Distribution of mood start → mood end pairs."""
        stmt = (
            select(
                SessionRecord.student_mood_start,
                SessionRecord.student_mood_end,
                func.count(SessionRecord.id).label("count"),
            )
            .where(
                SessionRecord.student_mood_start.isnot(None),
                SessionRecord.student_mood_end.isnot(None),
            )
            .group_by(SessionRecord.student_mood_start, SessionRecord.student_mood_end)
            .order_by(func.count(SessionRecord.id).desc())
        )
        result = await self.db.execute(stmt)
        return [
            {"mood_start": row[0], "mood_end": row[1], "count": row[2]}
            for row in result.all()
        ]

    async def dashboard_summary(self) -> dict[str, Any]:
        """Single call to get all key dashboard metrics."""
        status_counts = await self.session_counts_by_status()
        risk_counts = await self.session_counts_by_risk()
        avg_duration = await self.average_session_duration()
        avg_turns = await self.average_turn_count()
        follow_up = await self.follow_up_stats()
        feedback = await self.feedback_summary()

        total_sessions = sum(status_counts.values())
        completed = status_counts.get("completed", 0)

        return {
            "total_sessions": total_sessions,
            "completed_sessions": completed,
            "status_breakdown": status_counts,
            "risk_breakdown": risk_counts,
            "avg_duration_seconds": round(avg_duration, 1) if avg_duration else None,
            "avg_turn_count": round(avg_turns, 1) if avg_turns else None,
            "follow_up": follow_up,
            "feedback": feedback,
        }
