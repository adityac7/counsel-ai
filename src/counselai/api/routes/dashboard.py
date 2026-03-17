"""Dashboard API routes for counsellor, student, and school views."""

from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from sqlalchemy.orm import Session

from counselai.api.deps import get_sync_db
from counselai.api.schemas import (
    CounsellorQueueResponse,
    ProfileResponse,
    SchoolOverviewResponse,
    SessionStatus,
    StudentDashboardResponse,
    StudentSessionSummary,
)
from counselai.dashboard.counsellor import (
    QueueFilters,
    get_available_grades,
    get_available_schools,
    get_counsellor_queue,
    get_session_evidence,
    get_session_review,
)
from counselai.dashboard.school import SchoolAnalyticsService
from counselai.dashboard.student import build_student_dashboard

_PROJECT_ROOT = Path(__file__).resolve().parents[4]
templates = Jinja2Templates(directory=str(_PROJECT_ROOT / "templates"))

router = APIRouter()


# ---------------------------------------------------------------------------
# Counsellor Workbench — HTML pages (Task 12)
# ---------------------------------------------------------------------------


@router.get("/counsellor", response_class=HTMLResponse)
def counsellor_workbench(request: Request, db: Session = Depends(get_sync_db)):
    """Main counsellor workbench page."""
    schools = get_available_schools(db)
    grades = get_available_grades(db)
    return templates.TemplateResponse(
        "dashboard/counsellor.html",
        {"request": request, "schools": schools, "grades": grades, "active_nav": "students"},
    )


@router.get("/counsellor/sessions/{session_id}", response_class=HTMLResponse)
def counsellor_session_detail_page(
    request: Request,
    session_id: str,
    db: Session = Depends(get_sync_db),
):
    """Session review page for a single session."""
    try:
        sid = uuid.UUID(session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid session ID")

    data = get_session_review(db, sid)
    if data is None:
        raise HTTPException(status_code=404, detail="Session not found")

    return templates.TemplateResponse(
        "dashboard/counsellor_session.html",
        {"request": request, "data": data},
    )


# ---------------------------------------------------------------------------
# Counsellor Workbench — JSON APIs (Task 12)
# ---------------------------------------------------------------------------


@router.get("/counsellor/queue")
def counsellor_queue(
    school_id: str | None = Query(None),
    grade: str | None = Query(None),
    red_flag: bool | None = Query(None),
    status: str | None = Query(None),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    search: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_sync_db),
):
    """Sessions needing review, with optional filters."""
    filters = QueueFilters(
        school_id=school_id,
        grade=grade,
        red_flag=red_flag,
        status=status,
        date_from=date_from,
        date_to=date_to,
        search=search,
        limit=limit,
        offset=offset,
    )
    result = get_counsellor_queue(db, filters)
    return JSONResponse(result)


@router.get("/counsellor/sessions/{session_id}/review")
def counsellor_session_review(
    session_id: str,
    db: Session = Depends(get_sync_db),
):
    """Full session review data as JSON."""
    try:
        sid = uuid.UUID(session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid session ID")

    data = get_session_review(db, sid)
    if data is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return JSONResponse(data)


@router.get("/counsellor/sessions/{session_id}/evidence")
def counsellor_session_evidence(
    session_id: str,
    db: Session = Depends(get_sync_db),
):
    """Evidence explorer data for a session."""
    try:
        sid = uuid.UUID(session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid session ID")

    data = get_session_evidence(db, sid)
    if data is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return JSONResponse(data)


@router.get("/counsellor/filters")
def counsellor_filters(db: Session = Depends(get_sync_db)):
    """Available filter options for the counsellor queue."""
    return JSONResponse({
        "schools": get_available_schools(db),
        "grades": get_available_grades(db),
        "statuses": ["completed", "processing", "failed"],
    })


# ---------------------------------------------------------------------------
# Student API (Task 13)
# ---------------------------------------------------------------------------

@router.get("/students/{student_id}", response_model=StudentDashboardResponse)
def student_dashboard_api(student_id: str, db: Session = Depends(get_sync_db)):
    """Historical sessions and latest profile summary (JSON API)."""
    try:
        sid = uuid.UUID(student_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid student ID format")

    data = build_student_dashboard(db, sid)
    if data is None:
        raise HTTPException(status_code=404, detail="Student not found")

    sessions = []
    for snap in data["growth_snapshots"]:
        sessions.append(
            StudentSessionSummary(
                session_id=uuid.UUID(snap["session_id"]),
                case_study_id=snap["case_study_id"],
                status=SessionStatus.completed,
                started_at=snap["date"],
                summary=snap["summary"] or None,
            )
        )

    latest_profile = None
    latest = data["latest"]
    if latest.get("summary"):
        latest_profile = ProfileResponse(
            session_id=uuid.UUID(data["growth_snapshots"][0]["session_id"])
            if data["growth_snapshots"]
            else uuid.uuid4(),
            summary=latest["summary"],
        )

    return StudentDashboardResponse(
        student_id=uuid.UUID(data["student"]["id"]),
        full_name=data["student"]["full_name"],
        sessions=sessions,
        latest_profile=latest_profile,
    )


@router.get("/students/{student_id}/insights", response_class=HTMLResponse)
def student_insights_page(
    student_id: str,
    request: Request,
    db: Session = Depends(get_sync_db),
):
    """Student-facing insights page — strengths, interests, growth."""
    try:
        sid = uuid.UUID(student_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid student ID format")

    data = build_student_dashboard(db, sid)
    if data is None:
        raise HTTPException(status_code=404, detail="Student not found")

    return templates.TemplateResponse(
        "dashboard/student.html",
        {"request": request, "data": data},
    )


# ---------------------------------------------------------------------------
# School Analytics API (Task 14)
# ---------------------------------------------------------------------------

@router.get("/schools/{school_id}/overview", response_model=SchoolOverviewResponse)
def school_overview(
    school_id: str,
    grade: str | None = Query(None, description="Filter class-level insights to this grade"),
    trend: str = Query("month", description="Trend granularity: month or week"),
    db: Session = Depends(get_sync_db),
):
    """School-level aggregate analytics.

    Returns cohort distribution, red-flag volume, topic clusters,
    construct breakdowns, session trends, and optional class-level insights.
    All data is aggregate-only — no individual student details are exposed.
    """
    try:
        sid = uuid.UUID(school_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid school_id format")

    svc = SchoolAnalyticsService(db)
    data = svc.full_analytics(sid, grade=grade, trend_granularity=trend)

    if not data:
        raise HTTPException(status_code=404, detail="School not found")

    return data


@router.get("/schools/{school_id}/grades/{grade}", response_model=None)
def school_class_insights(
    school_id: str,
    grade: str,
    db: Session = Depends(get_sync_db),
):
    """Class-level aggregate insights for a specific grade.

    Separate endpoint for drill-down into a single grade without
    pulling the full school analytics payload.
    """
    try:
        sid = uuid.UUID(school_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid school_id format")

    svc = SchoolAnalyticsService(db)
    school = svc.get_school(sid)
    if school is None:
        raise HTTPException(status_code=404, detail="School not found")

    return svc.class_insights(sid, grade)


# ---------------------------------------------------------------------------
# School Analytics HTML page
# ---------------------------------------------------------------------------

@router.get("/schools/{school_id}/dashboard", response_class=HTMLResponse)
def school_dashboard_page(
    request: Request,
    school_id: str,
    db: Session = Depends(get_sync_db),
):
    """Render the school analytics dashboard HTML page."""
    try:
        sid = uuid.UUID(school_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid school_id format")

    svc = SchoolAnalyticsService(db)
    data = svc.full_analytics(sid)

    if not data:
        raise HTTPException(status_code=404, detail="School not found")

    return templates.TemplateResponse(
        "dashboard/school.html",
        {"request": request, "school": data},
    )
