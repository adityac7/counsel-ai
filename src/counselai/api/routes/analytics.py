"""Analytics REST API — dashboard stats, student progress, session trends."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from counselai.api.deps import get_db
from counselai.storage.models import SessionFeedback, SessionRecord, Student
from counselai.storage.repositories.analytics import AnalyticsRepository

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class DashboardResponse(BaseModel):
    total_sessions: int = 0
    completed_sessions: int = 0
    status_breakdown: dict[str, int] = Field(default_factory=dict)
    risk_breakdown: dict[str, int] = Field(default_factory=dict)
    avg_duration_seconds: float | None = None
    avg_turn_count: float | None = None
    follow_up: dict[str, int] = Field(default_factory=dict)
    feedback: dict[str, Any] = Field(default_factory=dict)


class StudentProgressEntry(BaseModel):
    session_id: str
    started_at: str
    status: str
    risk_level: str | None = None
    mood_start: str | None = None
    mood_end: str | None = None
    topics: list[str] = Field(default_factory=list)
    summary: str | None = None
    turn_count: int | None = None
    duration_seconds: int | None = None


class StudentProgressResponse(BaseModel):
    student_id: str
    full_name: str
    grade: str
    total_sessions: int = 0
    sessions: list[StudentProgressEntry] = Field(default_factory=list)


class TrendPoint(BaseModel):
    date: str
    count: int


class SessionTrendsResponse(BaseModel):
    granularity: str  # "day" or "week"
    points: list[TrendPoint] = Field(default_factory=list)


class TopicEntry(BaseModel):
    topic: str
    count: int


class TopicsResponse(BaseModel):
    topics: list[TopicEntry] = Field(default_factory=list)


class RiskBucket(BaseModel):
    level: str
    count: int
    pct: float


class RiskSummaryResponse(BaseModel):
    total_assessed: int = 0
    distribution: list[RiskBucket] = Field(default_factory=list)


class FeedbackCreateRequest(BaseModel):
    respondent: str = "student"
    rating: int | None = Field(None, ge=1, le=5)
    helpful: bool | None = None
    comments: str | None = None


class FeedbackResponse(BaseModel):
    id: str
    session_id: str
    respondent: str
    rating: int | None = None
    helpful: bool | None = None
    comments: str | None = None
    created_at: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/dashboard", response_model=DashboardResponse)
async def analytics_dashboard(db: AsyncSession = Depends(get_db)):
    """Overall dashboard stats — session counts, risk breakdown, feedback."""
    repo = AnalyticsRepository(db)
    data = await repo.dashboard_summary()
    return DashboardResponse(**data)


@router.get("/student/{student_id}/progress", response_model=StudentProgressResponse)
async def student_progress(
    student_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Student progress over time — all sessions ordered chronologically."""
    try:
        sid = uuid.UUID(student_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid student_id format")

    student = await db.get(Student, sid)
    if student is None:
        raise HTTPException(status_code=404, detail="Student not found")

    stmt = (
        select(SessionRecord)
        .where(SessionRecord.student_id == sid)
        .order_by(SessionRecord.started_at)
    )
    result = await db.execute(stmt)
    sessions = result.scalars().all()

    entries = []
    for s in sessions:
        topics = s.topics_discussed if isinstance(s.topics_discussed, list) else []
        entries.append(
            StudentProgressEntry(
                session_id=str(s.id),
                started_at=s.started_at.isoformat() if s.started_at else "",
                status=s.status or "",
                risk_level=s.risk_level,
                mood_start=s.student_mood_start,
                mood_end=s.student_mood_end,
                topics=topics,
                summary=s.session_summary,
                turn_count=s.turn_count,
                duration_seconds=s.duration_seconds,
            )
        )

    return StudentProgressResponse(
        student_id=str(student.id),
        full_name=student.full_name,
        grade=student.grade,
        total_sessions=len(entries),
        sessions=entries,
    )


@router.get("/sessions/trends", response_model=SessionTrendsResponse)
async def session_trends(
    days: int = Query(30, ge=1, le=365, description="Look-back window in days"),
    granularity: str = Query("day", description="'day' or 'week'"),
    db: AsyncSession = Depends(get_db),
):
    """Sessions per day or week over a rolling window."""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    repo = AnalyticsRepository(db)
    daily = await repo.sessions_per_day(since=since)

    if granularity == "week":
        week_buckets: dict[str, int] = {}
        for point in daily:
            dt = datetime.fromisoformat(point["date"]) if isinstance(point["date"], str) else point["date"]
            if isinstance(dt, str):
                dt = datetime.fromisoformat(dt)
            # ISO week start (Monday)
            if hasattr(dt, "isocalendar"):
                iso = dt.isocalendar()
                week_label = f"{iso[0]}-W{iso[1]:02d}"
            else:
                week_label = str(dt)
            week_buckets[week_label] = week_buckets.get(week_label, 0) + point["count"]
        points = [TrendPoint(date=k, count=v) for k, v in sorted(week_buckets.items())]
    else:
        points = [TrendPoint(date=str(p["date"]), count=p["count"]) for p in daily]

    return SessionTrendsResponse(granularity=granularity, points=points)


@router.get("/topics", response_model=TopicsResponse)
async def top_topics(
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """Most discussed topics across all sessions."""
    repo = AnalyticsRepository(db)
    raw = await repo.top_topics(limit=limit)
    return TopicsResponse(
        topics=[TopicEntry(topic=t["topic"], count=t["count"]) for t in raw]
    )


@router.get("/risk-summary", response_model=RiskSummaryResponse)
async def risk_summary(db: AsyncSession = Depends(get_db)):
    """Risk level distribution across assessed sessions."""
    repo = AnalyticsRepository(db)
    counts = await repo.session_counts_by_risk()
    total = sum(counts.values())
    distribution = [
        RiskBucket(
            level=level,
            count=count,
            pct=round(count / total * 100, 1) if total > 0 else 0.0,
        )
        for level, count in sorted(counts.items())
    ]
    return RiskSummaryResponse(total_assessed=total, distribution=distribution)


# ---------------------------------------------------------------------------
# Feedback endpoint (POST /api/sessions/{id}/feedback)
# ---------------------------------------------------------------------------
# Mounted separately at /api/sessions prefix — but defined here for cohesion.

feedback_router = APIRouter(prefix="/api/sessions", tags=["feedback"])


@feedback_router.post("/{session_id}/feedback", response_model=FeedbackResponse)
async def submit_feedback(
    session_id: str,
    body: FeedbackCreateRequest,
    db: AsyncSession = Depends(get_db),
):
    """Submit post-session feedback for a session."""
    try:
        sid = uuid.UUID(session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid session_id format")

    session = await db.get(SessionRecord, sid)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    fb = SessionFeedback(
        session_id=sid,
        respondent=body.respondent,
        rating=body.rating,
        helpful=body.helpful,
        comments=body.comments,
    )
    db.add(fb)
    await db.flush()

    return FeedbackResponse(
        id=str(fb.id),
        session_id=str(fb.session_id),
        respondent=fb.respondent,
        rating=fb.rating,
        helpful=fb.helpful,
        comments=fb.comments,
        created_at=fb.created_at.isoformat() if fb.created_at else "",
    )
