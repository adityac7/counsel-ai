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
from counselai.dashboard.counsellor_queue import (
    QueueFilters,
    get_available_grades,
    get_available_schools,
    get_counsellor_queue,
)
from counselai.dashboard.counsellor_review import (
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
        {"request": request, "schools": schools, "grades": grades},
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


# ---------------------------------------------------------------------------
# Student API (Task 13)
# ---------------------------------------------------------------------------

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
