"""Deterministic seed data for browser E2E runs against the live app DB."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from counselai.settings import settings
from counselai.storage.db import get_sync_session_factory, init_db
from counselai.storage.models import (
    Hypothesis,
    Profile,
    School,
    SessionRecord,
    Speaker,
    Student,
    Turn,
)

seeded_dashboard_data: dict[str, Any] | None = None

def _utc(day_offset: int, minutes: int) -> datetime:
    base = datetime(2026, 3, 17, 10, 0, tzinfo=timezone.utc)
    return base + timedelta(days=day_offset, minutes=minutes)


def _session(
    student: Student,
    *,
    case_study_id: str,
    status: str,
    started_at: datetime,
    duration_seconds: int | None,
    summary: str | None = None,
    risk_level: str | None = None,
) -> SessionRecord:
    ended_at = (
        started_at + timedelta(seconds=duration_seconds)
        if duration_seconds is not None
        else None
    )
    return SessionRecord(
        student=student,
        case_study_id=case_study_id,
        provider="gemini-live",
        status=status,
        started_at=started_at,
        ended_at=ended_at,
        duration_seconds=duration_seconds,
        processing_version="v1",
        primary_language="hinglish",
        session_summary=summary,
        risk_level=risk_level,
        follow_up_needed=bool(risk_level and risk_level != "low"),
    )

def _turns(session: SessionRecord, transcript: list[tuple[str, str, int, int]]) -> None:
    for idx, (speaker, text, start_ms, end_ms) in enumerate(transcript):
        session.turns.append(
            Turn(
                turn_index=idx,
                speaker=speaker,
                start_ms=start_ms,
                end_ms=end_ms,
                text=text,
                source="live_transcript",
                confidence=0.92 if speaker == Speaker.student.value else 0.97,
            )
        )


def _student_view_profile(
    session: SessionRecord,
    *,
    summary: str,
    encouragement: str,
    strengths: list[str],
    interests: list[str],
    growth_areas: list[str],
    next_steps: list[str],
) -> None:
    session.profiles.append(
        Profile(
            profile_version="v1",
            student_view_json={
                "summary": summary,
                "encouragement": encouragement,
                "strengths": strengths,
                "interests": interests,
                "growth_areas": growth_areas,
                "suggested_next_steps": next_steps,
            },
            counsellor_view_json={},
            school_view_json={},
            red_flags_json=[],
        )
    )

def _review_profile(session: SessionRecord) -> None:
    red_flags = [
        {
            "key": "peer_pressure",
            "severity": "high",
            "reason": "Student reports repeated pressure around smoking.",
            "recommended_action": "Check peer environment in the next session.",
        }
    ]
    session.profiles.append(
        Profile(
            profile_version="v1",
            student_view_json={
                "summary": "You are learning to hold your own boundaries.",
                "encouragement": "You already know what feels wrong to you.",
                "strengths": ["Self-awareness", "Reflection"],
                "interests": ["Sports leadership"],
                "growth_areas": ["Peer resistance"],
                "suggested_next_steps": ["Practice a refusal line"],
            },
            counsellor_view_json={
                "summary": "Student shows insight but remains vulnerable to group pressure.",
                "constructs": [
                    {
                        "key": "critical_thinking",
                        "label": "Critical Thinking",
                        "score": 0.72,
                        "status": "supported",
                        "evidence_summary": "Can explain tradeoffs and likely outcomes.",
                    },
                    {
                        "key": "confidence",
                        "label": "Confidence",
                        "score": 0.46,
                        "status": "mixed",
                        "evidence_summary": "Knows the preferred choice but hesitates socially.",
                    },
                ],
                "cross_modal_notes": [
                    "Speech softens when describing friend-group pressure."
                ],
                "recommended_follow_ups": [
                    "Follow up on smoking-related peer triggers.",
                    "Role-play a refusal response.",
                ],
            },
            school_view_json={"themes": ["peer_pressure"]},
            red_flags_json=red_flags,
        )
    )

    session.hypotheses.append(
        Hypothesis(
            construct_key="peer_resistance",
            label="Peer Resistance",
            score=0.55,
            status="mixed",
            evidence_summary="Student wants to resist but lacks a practiced script.",
            evidence_refs_json={"refs": ["turn:0", "turn:2"]},
        )
    )

def _legacy_report(session: SessionRecord) -> None:
    session.report = (
        '{"profile": {'
        '"summary": "Student feels isolated in the current section.",'
        '"cognitive_profile": {"critical_thinking": 7, "perspective_taking": 8},'
        '"emotional_profile": {"eq_score": 6, "stress_response": "withdraws"},'
        '"behavioral_insights": {"confidence": 4, "leadership_potential": "emerging"},'
        '"reasoning": {"critical_thinking": "Explains choices clearly.", "confidence": "Voice drops around classmates."},'
        '"red_flags": ["Mentions eating lunch alone most days."],'
        '"recommendations": ["Check social belonging and teacher support in the next session."]'
        '}}'
    )

def ensure_seeded_dashboard_data() -> dict[str, Any]:
    """Seed one deterministic browser dataset into the configured app DB."""
    global seeded_dashboard_data
    if seeded_dashboard_data is not None:
        return seeded_dashboard_data

    init_db(settings.database_url)
    session_factory = get_sync_session_factory()
    seed_tag = uuid.uuid4().hex[:8]

    db = session_factory()
    try:
        school_primary = School(name=f"E2E Primary School {seed_tag}", board="CBSE", city="Delhi")
        school_secondary = School(name=f"E2E Secondary School {seed_tag}", board="ICSE", city="Pune")
        db.add_all([school_primary, school_secondary])
        db.flush()

        history_student = Student(
            full_name=f"E2E History Student {seed_tag}",
            grade="10",
            section="A",
            age=15,
            school=school_primary,
            language_pref="hinglish",
        )
        review_student = Student(
            full_name=f"E2E Review Student {seed_tag}",
            grade="11",
            section="B",
            age=16,
            school=school_primary,
            language_pref="hinglish",
        )
        legacy_student = Student(
            full_name=f"E2E Legacy Student {seed_tag}",
            grade="9",
            section="C",
            age=14,
            school=school_secondary,
            language_pref="hinglish",
        )
        other_student = Student(
            full_name=f"E2E Other Student {seed_tag}",
            grade="12",
            section="A",
            age=17,
            school=school_secondary,
            language_pref="en",
        )
        db.add_all([history_student, review_student, legacy_student, other_student])
        db.flush()

        history_latest = _session(
            history_student,
            case_study_id="confidence-02",
            status="completed",
            started_at=_utc(-1, 20),
            duration_seconds=420,
            summary="Student is becoming more decisive.",
            risk_level="low",
        )
        history_previous = _session(
            history_student,
            case_study_id="peer-pressure-01",
            status="completed",
            started_at=_utc(-7, 15),
            duration_seconds=360,
            summary="Student identified pressure from friends.",
            risk_level="medium",
        )
        review_session = _session(
            review_student,
            case_study_id="peer-pressure-03",
            status="completed",
            started_at=_utc(0, 5),
            duration_seconds=305,
            summary="Student discussed peer pressure and smoking.",
            risk_level="high",
        )
        legacy_session = _session(
            legacy_student,
            case_study_id="belonging-02",
            status="completed",
            started_at=_utc(-2, 45),
            duration_seconds=250,
            summary="Legacy raw report fallback.",
            risk_level="medium",
        )
        processing_session = _session(
            other_student,
            case_study_id="career-01",
            status="processing",
            started_at=_utc(0, 30),
            duration_seconds=180,
            summary="Processing in progress.",
            risk_level=None,
        )
        failed_session = _session(
            review_student,
            case_study_id="stress-01",
            status="failed",
            started_at=_utc(-3, 10),
            duration_seconds=90,
            summary="Failed processing example.",
            risk_level=None,
        )

        db.add_all(
            [
                history_latest,
                history_previous,
                review_session,
                legacy_session,
                processing_session,
                failed_session,
            ]
        )
        db.flush()

        _turns(
            history_latest,
            [
                (Speaker.student.value, "I can say no more clearly now.", 0, 8000),
                (Speaker.counsellor.value, "What changed since last time?", 8500, 13000),
                (Speaker.student.value, "I practiced with my cousin.", 14000, 21000),
            ],
        )
        _turns(
            history_previous,
            [
                (Speaker.student.value, "My friends push me to bunk class.", 0, 9000),
                (Speaker.counsellor.value, "How do you react?", 9200, 13000),
            ],
        )
        _turns(
            review_session,
            [
                (Speaker.student.value, "They keep asking me to try smoking once.", 0, 9000),
                (Speaker.counsellor.value, "What do you feel in that moment?", 9200, 14500),
                (Speaker.student.value, "I know it is wrong but I freeze.", 15000, 28000),
            ],
        )
        _turns(
            legacy_session,
            [
                (Speaker.student.value, "I mostly sit alone at lunch.", 0, 8000),
                (Speaker.counsellor.value, "How long has that been happening?", 8200, 12600),
            ],
        )
        _turns(
            processing_session,
            [
                (Speaker.student.value, "I am confused about which stream to choose.", 0, 8200),
            ],
        )

        _student_view_profile(
            history_previous,
            summary="You are noticing when peer pressure starts to build.",
            encouragement="Recognizing the pattern is a strong first step.",
            strengths=["Observation", "Honesty"],
            interests=["Cricket"],
            growth_areas=["Boundary setting"],
            next_steps=["Notice who pressures you the most"],
        )
        _student_view_profile(
            history_latest,
            summary="You are getting clearer about your own choices.",
            encouragement="Your confidence is growing with practice.",
            strengths=["Self-awareness", "Communication"],
            interests=["Cricket", "Design"],
            growth_areas=["Consistency under pressure"],
            next_steps=["Practice one refusal line before the next session"],
        )
        _review_profile(review_session)
        _legacy_report(legacy_session)

        db.commit()

        seeded_dashboard_data = {
            "schools": [str(school_primary.id), str(school_secondary.id)],
            "students": {
                "history": str(history_student.id),
                "review": str(review_student.id),
                "legacy": str(legacy_student.id),
                "other": str(other_student.id),
            },
            "sessions": {
                "history_latest": str(history_latest.id),
                "history_previous": str(history_previous.id),
                "review": str(review_session.id),
                "legacy": str(legacy_session.id),
                "processing": str(processing_session.id),
                "failed": str(failed_session.id),
            },
            "names": {
                "history_student": history_student.full_name,
                "review_student": review_student.full_name,
                "legacy_student": legacy_student.full_name,
                "school_primary": school_primary.name,
                "school_secondary": school_secondary.name,
                "session_profile_summary": "Student shows insight but remains vulnerable to group pressure.",
            },
        }
        return seeded_dashboard_data
    finally:
        db.close()
