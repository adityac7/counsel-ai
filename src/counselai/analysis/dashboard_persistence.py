"""Persistence helpers for analysis results consumed by dashboard readers."""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from sqlalchemy.orm import Session

from counselai.storage.models import (
    Hypothesis,
    Profile,
    School,
    SessionRecord,
    SessionTokenUsage,
)

logger = logging.getLogger(__name__)

ANALYZE_SESSION_PROFILE_VERSION = "analyze-session-v1"


def _normalize_red_flags(raw_flags: list) -> list[dict[str, Any]]:
    """Ensure red_flags_json always stores {key, severity, reason} objects."""
    normalized = []
    for flag in raw_flags:
        if isinstance(flag, str):
            normalized.append({"key": flag, "severity": "medium", "reason": flag})
        elif isinstance(flag, dict):
            normalized.append({
                "key": flag.get("key") or flag.get("flag") or "unknown",
                "severity": flag.get("severity", "medium"),
                "reason": flag.get("reason") or flag.get("description") or "",
            })
    return normalized


def _normalize_student_view(view: dict[str, Any]) -> dict[str, Any]:
    """Ensure student_view_json includes both next_steps and suggested_next_steps."""
    if not isinstance(view, dict):
        view = {}
    steps = view.get("next_steps") or view.get("suggested_next_steps") or []
    view["next_steps"] = steps
    view["suggested_next_steps"] = steps
    return view


def _normalize_counsellor_view(view: dict[str, Any]) -> dict[str, Any]:
    """Ensure counsellor_view_json includes summary, constructs, recommended_follow_ups."""
    if not isinstance(view, dict):
        view = {}
    view.setdefault("summary", "")
    view.setdefault("constructs", [])
    follow_up = view.get("follow_up") or {}
    view.setdefault("recommended_follow_ups", follow_up.get("actions", []))
    return view


def _get_or_create_school(db: Session, school_name: str) -> School | None:
    clean_name = school_name.strip()
    if not clean_name:
        return None

    school = db.query(School).filter(School.name == clean_name).first()
    if school is not None:
        return school

    school = School(name=clean_name)
    db.add(school)
    db.flush()
    return school


def _highest_risk_level(red_flags: list[dict[str, Any]]) -> str | None:
    if not red_flags:
        return None

    severity_rank = {"low": 1, "medium": 2, "high": 3, "critical": 4}
    best = "low"
    best_rank = 1
    for flag in red_flags:
        severity = str(flag.get("severity") or "medium").lower()
        rank = severity_rank.get(severity, 2)
        if rank > best_rank:
            best = severity
            best_rank = rank
    return best


def _upsert_profile(
    db: Session,
    *,
    session_id: uuid.UUID,
    dashboard_payload: dict[str, Any],
) -> None:
    profile = (
        db.query(Profile)
        .filter(
            Profile.session_id == session_id,
            Profile.profile_version == ANALYZE_SESSION_PROFILE_VERSION,
        )
        .order_by(Profile.created_at.desc())
        .first()
    )

    if profile is None:
        profile = Profile(
            session_id=session_id,
            profile_version=ANALYZE_SESSION_PROFILE_VERSION,
        )
        db.add(profile)

    # Use .get() with sensible defaults so a missing subtree does not abort
    # persistence — we'd rather record partial data than drop everything.
    profile.student_view_json = dashboard_payload.get("student_view") or {}
    profile.counsellor_view_json = dashboard_payload.get("counsellor_view") or {}
    profile.school_view_json = dashboard_payload.get("school_view") or {}
    profile.red_flags_json = dashboard_payload.get("red_flags") or []
    db.flush()


def _upsert_hypotheses(
    db: Session,
    *,
    session_id: uuid.UUID,
    hypotheses: list[dict[str, Any]],
) -> None:
    # Delete all existing hypotheses for this session first to prevent stale/duplicate constructs
    db.query(Hypothesis).filter(Hypothesis.session_id == session_id).delete()

    for item in hypotheses:
        construct_key = item.get("construct_key")
        if not construct_key:
            continue

        row = Hypothesis(
            session_id=session_id,
            construct_key=construct_key,
            label=item["label"],
            status=item["status"],
            score=item["score"],
            evidence_summary=item["evidence_summary"],
            evidence_refs_json=item.get("evidence_refs", {}),
        )
        db.add(row)

    db.flush()


def persist_session_analysis(
    db: Session,
    *,
    session_id: uuid.UUID,
    report_data: dict[str, Any],
    dashboard_payload: dict[str, Any],
    student_name: str,
    student_grade: str,
    student_section: str,
    student_school: str,
    student_age: int,
) -> bool:
    """Persist analysis artifacts onto the existing live session.

    This function is intentionally tolerant of partial payloads: if a
    specific subtree (``student_view``, ``counsellor_view``, ``school_view``,
    ``red_flags``, ``hypotheses``) is missing, a WARNING is logged and the
    function continues with the subtrees that *are* present. Previously a
    missing key would raise ``KeyError`` and abort the entire write — that
    behaviour was the root cause of "analysis not saved properly" when the
    LLM response omitted a single field.
    """
    session = db.get(SessionRecord, session_id)
    if session is None:
        logger.warning("persist_session_analysis: session %s not found", session_id)
        return False

    session.report = json.dumps(report_data, default=str)
    session.processing_version = ANALYZE_SESSION_PROFILE_VERSION

    # Warn about missing required subtrees; empty red_flags/hypotheses is normal.
    for key in ("student_view", "counsellor_view", "school_view"):
        if not dashboard_payload.get(key):
            logger.warning(
                "persist_session_analysis: dashboard_payload missing/empty %r — persisting remaining subtrees",
                key,
            )
    if not dashboard_payload.get("red_flags"):
        logger.debug("persist_session_analysis: no red_flags (no risk detected — normal)")
    if not dashboard_payload.get("hypotheses"):
        logger.warning("persist_session_analysis: dashboard_payload missing/empty 'hypotheses'")

    # Normalize shapes before persisting
    student_view = _normalize_student_view(dashboard_payload.get("student_view") or {})
    counsellor_view = _normalize_counsellor_view(dashboard_payload.get("counsellor_view") or {})
    school_view = dashboard_payload.get("school_view") or {}
    red_flags = _normalize_red_flags(dashboard_payload.get("red_flags") or [])

    # Write normalized shapes back so _upsert_profile stores canonical data
    dashboard_payload["student_view"] = student_view
    dashboard_payload["counsellor_view"] = counsellor_view
    dashboard_payload["school_view"] = school_view
    dashboard_payload["red_flags"] = red_flags

    session.session_summary = (
        counsellor_view.get("summary")
        or student_view.get("summary")
        or session.session_summary
    )
    session.risk_level = _highest_risk_level(red_flags)

    follow_up_actions = dashboard_payload.get("follow_up_actions") or counsellor_view.get("recommended_follow_ups") or []
    session.follow_up_needed = bool(
        red_flags
        or follow_up_actions
        or student_view.get("next_steps")
    )
    themes = school_view.get("themes") if isinstance(school_view, dict) else None
    if themes:
        session.topics_discussed = themes

    student = session.student
    if student is not None:
        clean_name = student_name.strip()
        clean_grade = student_grade.strip()
        clean_section = student_section.strip()
        if clean_name:
            student.full_name = clean_name
        if clean_grade:
            student.grade = clean_grade
        if clean_section:
            student.section = clean_section
        if student_age:
            student.age = student_age

        school = _get_or_create_school(db, student_school)
        if school is not None:
            student.school_id = school.id

    _upsert_profile(db, session_id=session_id, dashboard_payload=dashboard_payload)
    _upsert_hypotheses(
        db,
        session_id=session_id,
        hypotheses=dashboard_payload.get("hypotheses") or [],
    )

    db.flush()
    return True


def persist_session_usage(
    db: Session,
    *,
    session_id: uuid.UUID,
    input_tokens: int,
    output_tokens: int,
    cached_tokens: int,
    total_tokens: int,
    model: str,
    input_modality: dict | None = None,
    output_modality: dict | None = None,
) -> SessionTokenUsage:
    """Upsert a ``SessionTokenUsage`` row for the given session.

    One row per session (unique on ``session_id``). If an existing row is
    found it is updated in-place; otherwise a new row is inserted. The caller
    is expected to commit/flush the enclosing transaction.
    """
    existing = (
        db.query(SessionTokenUsage)
        .filter(SessionTokenUsage.session_id == session_id)
        .one_or_none()
    )

    im_json = json.dumps(input_modality) if input_modality else None
    om_json = json.dumps(output_modality) if output_modality else None

    if existing is None:
        row = SessionTokenUsage(
            session_id=session_id,
            model=model,
            input_tokens=int(input_tokens or 0),
            output_tokens=int(output_tokens or 0),
            cached_tokens=int(cached_tokens or 0),
            total_tokens=int(total_tokens or 0),
            input_modality_json=im_json,
            output_modality_json=om_json,
        )
        db.add(row)
        db.flush()
        return row

    existing.model = model
    existing.input_tokens = int(input_tokens or 0)
    existing.output_tokens = int(output_tokens or 0)
    existing.cached_tokens = int(cached_tokens or 0)
    existing.total_tokens = int(total_tokens or 0)
    if im_json is not None:
        existing.input_modality_json = im_json
    if om_json is not None:
        existing.output_modality_json = om_json
    db.flush()
    return existing


def add_analysis_tokens(
    db: Session,
    *,
    session_id: uuid.UUID,
    input_tokens: int,
    output_tokens: int,
    model: str,
) -> None:
    """Add analysis-call token counts on top of an existing ``SessionTokenUsage`` row.

    Called after the post-session Gemini analysis completes. If no live-session
    usage row exists yet, creates a minimal one.
    """
    existing = (
        db.query(SessionTokenUsage)
        .filter(SessionTokenUsage.session_id == session_id)
        .one_or_none()
    )

    if existing is None:
        row = SessionTokenUsage(
            session_id=session_id,
            model=model,
            input_tokens=0,
            output_tokens=0,
            cached_tokens=0,
            total_tokens=0,
            analysis_input_tokens=int(input_tokens or 0),
            analysis_output_tokens=int(output_tokens or 0),
        )
        db.add(row)
    else:
        existing.analysis_input_tokens = (existing.analysis_input_tokens or 0) + int(input_tokens or 0)
        existing.analysis_output_tokens = (existing.analysis_output_tokens or 0) + int(output_tokens or 0)
    db.flush()
