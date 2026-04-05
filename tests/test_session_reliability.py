"""Regression tests for session-end persistence and dashboard fallback rendering."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import uuid

import pytest
from fastapi.testclient import TestClient

from counselai.api.app import app
from counselai.dashboard.counsellor_review import get_session_review
from counselai.dashboard.school import SchoolAnalyticsService
from counselai.dashboard.student import build_student_dashboard
from counselai.storage.db import (
    close_db,
    create_all_tables,
    get_sync_session_factory,
    init_db,
)
from counselai.storage.models import Hypothesis, Profile, School, SessionRecord, Student


@pytest.fixture
def isolated_db():
    with TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "session-reliability.db"
        asyncio.run(close_db())
        init_db(f"sqlite+aiosqlite:///{db_path}")
        asyncio.run(create_all_tables())
        try:
            yield get_sync_session_factory()
        finally:
            asyncio.run(close_db())


def _seed_session(
    session_factory,
    *,
    report: dict | None = None,
    school_name: str | None = "Test School",
) -> tuple[str, datetime, datetime]:
    db = session_factory()
    try:
        school = None
        if school_name:
            school = School(name=school_name)
            db.add(school)
            db.flush()

        student = Student(
            full_name="Arjun Sharma",
            grade="10",
            section="B",
            age=15,
            school_id=school.id if school else None,
        )
        db.add(student)
        db.flush()

        started_at = datetime(2026, 3, 17, 10, 0, tzinfo=timezone.utc)
        ended_at = started_at + timedelta(minutes=2, seconds=5)
        session_record = SessionRecord(
            id=uuid.uuid4(),
            student_id=student.id,
            case_study_id="peer-pressure-01",
            provider="gemini-live",
            status="completed",
            started_at=started_at,
            ended_at=ended_at,
            duration_seconds=125,
            report=json.dumps(report) if report is not None else None,
        )
        db.add(session_record)
        db.commit()
        return str(session_record.id), started_at, ended_at
    finally:
        db.close()


def test_analyze_session_persists_report_without_overwriting_timing(isolated_db, monkeypatch):
    # Unified analyzer output shape (matches ANALYSIS_SCHEMA)
    raw_profile = {
        "session_summary": "Student shows steady judgement.",
        "engagement_score": 7,
        "key_themes": [{"theme": "peer_pressure", "evidence": "Friends pressure to smoke", "severity": "medium"}],
        "emotional_analysis": {
            "primary_emotion": "concern",
            "secondary_emotions": [],
            "trajectory": "steady",
            "emotional_vocabulary": "developing",
        },
        "risk_assessment": {
            "level": "moderate",
            "flags": [{"key": "peer_pressure", "severity": "medium", "reason": "Mentions peer pressure around smoking."}],
            "protective_factors": ["strong moral compass"],
            "immediate_safety_concern": False,
        },
        "constructs": [
            {"key": "critical_thinking", "label": "Critical Thinking", "score": 0.8, "status": "supported", "evidence_summary": "Student explains choices clearly."},
            {"key": "perspective_taking", "label": "Perspective Taking", "score": 0.7, "status": "supported", "evidence_summary": "Student considers other viewpoints."},
            {"key": "eq_score", "label": "EQ Score", "score": 0.6, "status": "mixed", "evidence_summary": "Student notices emotional impact."},
            {"key": "confidence", "label": "Confidence", "score": 0.5, "status": "mixed", "evidence_summary": "Student speaks cautiously but clearly."},
        ],
        "personality_snapshot": {"traits": ["Reflective", "Calm"], "communication_style": "concise", "decision_making": "deliberate"},
        "cognitive_profile": {"critical_thinking": 8, "perspective_taking": 7},
        "emotional_profile": {"eq_score": 6, "empathy_level": "moderate", "stress_response": "calm"},
        "behavioral_insights": {"confidence": 5, "resilience": "steady"},
        "key_moments": [{"quote": "My friends pressure me", "insight": "Shows awareness of peer influence."}],
        "student_view": {
            "strengths": ["Reflective", "Calm"],
            "interests": [],
            "growth_areas": ["Assertiveness"],
            "encouragement": "Your thoughtfulness shows real maturity.",
            "next_steps": ["Follow up on peer pressure triggers."],
        },
        "school_view": {"themes": ["peer_pressure"], "academic_pressure_level": "none"},
        "follow_up": {"actions": ["Follow up on peer pressure triggers."], "referral_needed": False, "urgency": "routine"},
        "red_flags": ["Mentions peer pressure around smoking."],
        "recommendations": ["Follow up on peer pressure triggers."],
    }
    session_id, started_at, ended_at = _seed_session(isolated_db)

    monkeypatch.setattr(
        "counselai.analysis.unified_analyzer.analyze_session",
        lambda *args, **kwargs: raw_profile,
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/analyze-session",
            data={
                "transcript": json.dumps(
                    [
                        {"role": "student", "text": "My friends pressure me to smoke."},
                        {"role": "counsellor", "text": "What do you do then?"},
                    ]
                ),
                "student_name": "Arjun Sharma",
                "student_class": "10",
                "student_section": "B",
                "student_school": "Test School",
                "student_age": "15",
                "session_start_time": started_at.isoformat(),
                "session_end_time": ended_at.isoformat(),
                "session_id": session_id,
            },
        )

    assert response.status_code == 200
    assert response.json()["profile"]["session_summary"] == raw_profile["session_summary"]

    db = isolated_db()
    try:
        saved = db.get(SessionRecord, uuid.UUID(session_id))
        assert saved is not None
        assert saved.duration_seconds == 125
        assert saved.ended_at.replace(tzinfo=timezone.utc) == ended_at
        assert saved.report is not None

        persisted_report = json.loads(saved.report)
        assert persisted_report["profile_raw"]["session_summary"] == raw_profile["session_summary"]

        profile_row = (
            db.query(Profile)
            .filter(Profile.session_id == saved.id)
            .order_by(Profile.created_at.desc())
            .first()
        )
        assert profile_row is not None
        assert profile_row.student_view_json is not None
        assert profile_row.red_flags_json is not None
        assert len(profile_row.red_flags_json) >= 1

        hypotheses = (
            db.query(Hypothesis)
            .filter(Hypothesis.session_id == saved.id)
            .all()
        )
        assert {row.construct_key for row in hypotheses} >= {
            "critical_thinking",
            "perspective_taking",
            "eq_score",
            "confidence",
        }

        student_dashboard = build_student_dashboard(db, saved.student_id)
        assert student_dashboard is not None
        assert student_dashboard["latest"] is not None

        school_analytics = SchoolAnalyticsService(db).full_analytics(
            saved.student.school_id
        )
        assert school_analytics["red_flag_summary"]["total_flags"] >= 1
        assert any(
            item["construct_key"] == "critical_thinking"
            for item in school_analytics["construct_distribution"]
        )
    finally:
        db.close()


def test_get_session_review_normalizes_raw_report_profile(isolated_db):
    raw_profile = {
        "summary": "Student is reflective and cautious.",
        "cognitive_profile": {"critical_thinking": 7, "perspective_taking": 8},
        "emotional_profile": {"eq_score": 6},
        "behavioral_insights": {"confidence": 4},
        "reasoning": {"critical_thinking": "Student reasons in steps."},
        "red_flags": ["Mentions feeling isolated in class."],
        "recommendations": ["Check social support in the next session."],
    }
    session_id, _, _ = _seed_session(isolated_db, report={"profile": raw_profile})

    db = isolated_db()
    try:
        review = get_session_review(db, uuid.UUID(session_id))
    finally:
        db.close()

    assert review is not None
    assert review["duration_seconds"] == 125
    # Legacy report fallback: profile is returned as-is from the report JSON
    assert review["profile"] is not None
    assert review["profile"]["summary"] == raw_profile["summary"]
    assert review["profile"]["red_flags"] == raw_profile["red_flags"]
    assert review["profile"]["recommendations"] == raw_profile["recommendations"]


def test_analyze_session_backfills_school_link_for_school_dashboard(isolated_db, monkeypatch):
    # Unified analyzer output shape (matches ANALYSIS_SCHEMA)
    raw_profile = {
        "session_summary": "Student wants more confidence in group settings.",
        "engagement_score": 6,
        "key_themes": [{"theme": "confidence", "evidence": "Hard to say no in groups", "severity": "medium"}],
        "emotional_analysis": {
            "primary_emotion": "uncertainty",
            "secondary_emotions": [],
            "trajectory": "steady",
            "emotional_vocabulary": "developing",
        },
        "risk_assessment": {
            "level": "low",
            "flags": [{"key": "peer_pressure", "severity": "medium", "reason": "Mentions pressure to fit in with a new group."}],
            "protective_factors": [],
            "immediate_safety_concern": False,
        },
        "constructs": [
            {"key": "confidence", "label": "Confidence", "score": 0.4, "status": "mixed", "evidence_summary": "Student hesitates when describing peer pressure."},
        ],
        "personality_snapshot": {"traits": ["Thoughtful"], "communication_style": "reserved", "decision_making": "cautious"},
        "cognitive_profile": {"critical_thinking": 7, "perspective_taking": 7},
        "emotional_profile": {"eq_score": 6, "empathy_level": "moderate", "stress_response": "withdraws"},
        "behavioral_insights": {"confidence": 4, "resilience": "developing"},
        "key_moments": [],
        "student_view": {
            "strengths": ["Thoughtful"],
            "interests": [],
            "growth_areas": ["Assertiveness"],
            "encouragement": "You are learning to hold your ground.",
            "next_steps": ["Practice one boundary-setting line before the next session."],
        },
        "school_view": {"themes": ["peer_pressure"], "academic_pressure_level": "none"},
        "follow_up": {"actions": ["Practice boundary-setting"], "referral_needed": False, "urgency": "routine"},
        "red_flags": ["Mentions pressure to fit in with a new group."],
        "recommendations": ["Practice one boundary-setting line before the next session."],
    }
    session_id, started_at, ended_at = _seed_session(isolated_db, school_name=None)

    monkeypatch.setattr(
        "counselai.analysis.unified_analyzer.analyze_session",
        lambda *args, **kwargs: raw_profile,
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/analyze-session",
            data={
                "transcript": json.dumps(
                    [{"role": "student", "text": "I find it hard to say no in groups."}]
                ),
                "student_name": "Arjun Sharma",
                "student_class": "10",
                "student_section": "B",
                "student_school": "Backfill School",
                "student_age": "15",
                "session_start_time": started_at.isoformat(),
                "session_end_time": ended_at.isoformat(),
                "session_id": session_id,
            },
        )

    assert response.status_code == 200

    db = isolated_db()
    try:
        saved = db.get(SessionRecord, uuid.UUID(session_id))
        assert saved is not None
        assert saved.student.school is not None
        assert saved.student.school.name == "Backfill School"

        school_data = SchoolAnalyticsService(db).full_analytics(saved.student.school_id)
        assert school_data["total_sessions"] == 1
        assert school_data["red_flag_summary"]["total_flags"] >= 1
    finally:
        db.close()
