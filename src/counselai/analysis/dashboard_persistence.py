"""Persistence helpers for analysis results consumed by dashboard readers."""

from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy.orm import Session

from counselai.storage.models import Hypothesis, Profile, School, SessionRecord

ANALYZE_SESSION_PROFILE_VERSION = "analyze-session-v1"


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

    profile.student_view_json = dashboard_payload["student_view"]
    profile.counsellor_view_json = dashboard_payload["counsellor_view"]
    profile.school_view_json = dashboard_payload["school_view"]
    profile.red_flags_json = dashboard_payload["red_flags"]
    db.flush()


def _upsert_hypotheses(
    db: Session,
    *,
    session_id: uuid.UUID,
    hypotheses: list[dict[str, Any]],
) -> None:
    construct_keys = [item["construct_key"] for item in hypotheses if item.get("construct_key")]
    if not construct_keys:
        return

    existing_rows = (
        db.query(Hypothesis)
        .filter(
            Hypothesis.session_id == session_id,
            Hypothesis.construct_key.in_(construct_keys),
        )
        .all()
    )
    existing_by_key = {row.construct_key: row for row in existing_rows}
    seen_keys: set[str] = set()

    for item in hypotheses:
        construct_key = item.get("construct_key")
        if not construct_key:
            continue

        seen_keys.add(construct_key)
        row = existing_by_key.get(construct_key)
        if row is None:
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
            continue

        row.label = item["label"]
        row.status = item["status"]
        row.score = item["score"]
        row.evidence_summary = item["evidence_summary"]
        row.evidence_refs_json = item.get("evidence_refs", {})

    for construct_key, row in existing_by_key.items():
        if construct_key not in seen_keys:
            db.delete(row)

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
    """Persist analysis artifacts onto the existing live session."""
    session = db.get(SessionRecord, session_id)
    if session is None:
        return False

    session.report = json.dumps(report_data, default=str)

    student_view = dashboard_payload["student_view"]
    counsellor_view = dashboard_payload["counsellor_view"]
    school_view = dashboard_payload["school_view"]
    red_flags = dashboard_payload["red_flags"]

    session.session_summary = (
        counsellor_view.get("summary")
        or student_view.get("summary")
        or session.session_summary
    )
    session.risk_level = _highest_risk_level(red_flags)
    session.follow_up_needed = bool(
        red_flags
        or counsellor_view.get("recommended_follow_ups")
        or student_view.get("suggested_next_steps")
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
        hypotheses=dashboard_payload["hypotheses"],
    )

    db.flush()
    return True
