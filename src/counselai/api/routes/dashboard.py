"""Dashboard API routes for counsellor, student, and school views."""

from __future__ import annotations

import uuid
from datetime import date
from typing import List

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from sqlalchemy.orm import Session

from counselai.storage.db import get_sync_db
from counselai.storage.models import (
    CaseStudy as CaseStudyRow,
    SessionRecord,
    SessionTokenUsage,
    Student,
)
from counselai.case_studies import (
    CATEGORY_PREFIXES,
    generate_case_study_id,
    get_all_case_studies,
    get_case_study_by_id,
    is_builtin,
)
from counselai.dashboard.counsellor_service import (
    QueueFilters,
    get_available_grades,
    get_available_schools,
    get_counsellor_queue,
    get_session_evidence,
    get_session_review,
)

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
        request=request, name="dashboard/counsellor.html",
        context={"schools": schools, "grades": grades},
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

    case_study_title = None
    cs_id = data["session"].get("case_study_id")
    if cs_id:
        cs = get_case_study_by_id(cs_id, db)
        if cs:
            case_study_title = cs["title"]

    return templates.TemplateResponse(
        request=request, name="dashboard/counsellor_session.html",
        context={"data": data, "case_study_title": case_study_title},
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
# Token Usage — HTML page
# ---------------------------------------------------------------------------


@router.get("/tokens", response_class=HTMLResponse)
def token_usage_page(request: Request, db: Session = Depends(get_sync_db)):
    """Per-session Gemini token usage overview."""
    rows_q = (
        db.query(SessionTokenUsage, SessionRecord, Student)
        .join(SessionRecord, SessionTokenUsage.session_id == SessionRecord.id)
        .outerjoin(Student, SessionRecord.student_id == Student.id)
        .order_by(SessionTokenUsage.created_at.desc())
        .limit(50)
        .all()
    )

    rows = []
    import json as _json
    total_input = total_output = total_cached = total_total = 0
    for usage, session, student in rows_q:
        live_in = usage.input_tokens or 0
        live_out = usage.output_tokens or 0
        ana_in = usage.analysis_input_tokens or 0
        ana_out = usage.analysis_output_tokens or 0
        grand_total = live_in + live_out + ana_in + ana_out

        total_input += live_in + ana_in
        total_output += live_out + ana_out
        total_cached += usage.cached_tokens or 0
        total_total += grand_total

        try:
            in_mod = _json.loads(usage.input_modality_json) if usage.input_modality_json else {}
        except Exception:
            in_mod = {}
        try:
            out_mod = _json.loads(usage.output_modality_json) if usage.output_modality_json else {}
        except Exception:
            out_mod = {}

        rows.append({
            "created_at": usage.created_at,
            "student_name": student.full_name if student else "—",
            "student_grade": student.grade if student else None,
            "model": usage.model,
            "input_tokens": live_in,
            "output_tokens": live_out,
            "cached_tokens": usage.cached_tokens or 0,
            "total_tokens": usage.total_tokens or 0,
            "input_modality": in_mod,
            "output_modality": out_mod,
            "analysis_input_tokens": ana_in,
            "analysis_output_tokens": ana_out,
            "grand_total": grand_total,
            "session_id": str(session.id) if session else None,
        })

    totals = {
        "sessions": len(rows),
        "input_tokens": total_input,
        "output_tokens": total_output,
        "cached_tokens": total_cached,
        "total_tokens": total_total,
    }

    return templates.TemplateResponse(
        request=request, name="dashboard/tokens.html",
        context={"rows": rows, "totals": totals},
    )


# ---------------------------------------------------------------------------
# Case Studies — HTML pages + create/list
# ---------------------------------------------------------------------------


@router.get("/case-studies", response_class=HTMLResponse)
def case_studies_list(request: Request, db: Session = Depends(get_sync_db)):
    """All case studies (built-in + custom) in a browseable list."""
    all_cs = get_all_case_studies(db)
    categories = sorted(set(cs["category"] for cs in all_cs))
    return templates.TemplateResponse(
        request=request, name="dashboard/case_studies.html",
        context={"case_studies": all_cs, "categories": categories},
    )


@router.get("/case-studies/new", response_class=HTMLResponse)
def case_study_new_form(request: Request, db: Session = Depends(get_sync_db)):
    """Blank form to create a new case study."""
    categories = list(CATEGORY_PREFIXES.keys())
    return templates.TemplateResponse(
        request=request, name="dashboard/case_study_new.html",
        context={"categories": categories, "error": None},
    )


@router.post("/case-studies")
def case_study_create(
    request: Request,
    title: str = Form(...),
    category: str = Form(...),
    target_class: str = Form(...),
    scenario_text: str = Form(...),
    scenario_text_hi: str = Form(""),
    probing_angle: List[str] = Form(default=[]),
    db: Session = Depends(get_sync_db),
):
    """Save a new custom case study and redirect to the list."""
    # Filter out blank probing angles
    angles = [a.strip() for a in probing_angle if a.strip()]

    # Validate required fields
    if not title.strip() or not scenario_text.strip():
        categories = list(CATEGORY_PREFIXES.keys())
        return templates.TemplateResponse(
            request=request, name="dashboard/case_study_new.html",
            context={
                "categories": categories,
                "error": "Title and scenario text are required.",
                "form": {
                    "title": title, "category": category,
                    "target_class": target_class,
                    "scenario_text": scenario_text,
                    "scenario_text_hi": scenario_text_hi,
                    "probing_angles": angles,
                },
            },
            status_code=422,
        )

    cs_id = generate_case_study_id(category, db)
    row = CaseStudyRow(
        id=cs_id,
        title=title.strip(),
        category=category,
        target_class=target_class,
        scenario_text=scenario_text.strip(),
        scenario_text_hi=scenario_text_hi.strip() or None,
        probing_angles=angles,
    )
    db.add(row)
    db.commit()

    return RedirectResponse(
        url="/api/v1/dashboard/case-studies",
        status_code=303,
    )


@router.get("/case-studies/{cs_id}/edit", response_class=HTMLResponse)
def case_study_edit_form(
    request: Request,
    cs_id: str,
    db: Session = Depends(get_sync_db),
):
    """Pre-filled edit form for an existing case study."""
    cs = get_case_study_by_id(cs_id, db)
    if cs is None:
        raise HTTPException(status_code=404, detail="Case study not found")
    categories = list(CATEGORY_PREFIXES.keys())
    return templates.TemplateResponse(
        request=request, name="dashboard/case_study_edit.html",
        context={
            "cs": cs,
            "categories": categories,
            "is_builtin": is_builtin(cs_id),
            "error": None,
        },
    )


@router.post("/case-studies/{cs_id}/edit")
def case_study_update(
    request: Request,
    cs_id: str,
    title: str = Form(...),
    category: str = Form(...),
    target_class: str = Form(...),
    scenario_text: str = Form(...),
    scenario_text_hi: str = Form(""),
    probing_angle: List[str] = Form(default=[]),
    db: Session = Depends(get_sync_db),
):
    """Update (upsert) a case study. Built-ins get a DB override row."""
    angles = [a.strip() for a in probing_angle if a.strip()]

    if not title.strip() or not scenario_text.strip():
        cs = get_case_study_by_id(cs_id, db)
        categories = list(CATEGORY_PREFIXES.keys())
        return templates.TemplateResponse(
            request=request, name="dashboard/case_study_edit.html",
            context={
                "cs": cs,
                "categories": categories,
                "is_builtin": is_builtin(cs_id),
                "error": "Title and scenario text are required.",
                "form": {
                    "title": title, "category": category,
                    "target_class": target_class,
                    "scenario_text": scenario_text,
                    "scenario_text_hi": scenario_text_hi,
                    "probing_angles": angles,
                },
            },
            status_code=422,
        )

    row = db.query(CaseStudyRow).filter(CaseStudyRow.id == cs_id).first()
    if row is None:
        # Built-in being edited for the first time — create a DB override
        row = CaseStudyRow(id=cs_id)
        db.add(row)

    row.title = title.strip()
    row.category = category
    row.target_class = target_class
    row.scenario_text = scenario_text.strip()
    row.scenario_text_hi = scenario_text_hi.strip() or None
    row.probing_angles = angles
    db.commit()

    return RedirectResponse(
        url="/api/v1/dashboard/case-studies",
        status_code=303,
    )


@router.post("/case-studies/{cs_id}/delete")
def case_study_delete(
    cs_id: str,
    db: Session = Depends(get_sync_db),
):
    """Delete a DB-stored case study. For built-in overrides this restores the original."""
    row = db.query(CaseStudyRow).filter(CaseStudyRow.id == cs_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Case study not found in database")
    db.delete(row)
    db.commit()
    return RedirectResponse(
        url="/api/v1/dashboard/case-studies",
        status_code=303,
    )

