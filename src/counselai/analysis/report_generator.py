"""Post-session report generator — produces structured counselling reports.

Takes a completed session's transcript and generates a comprehensive report
using Gemini (non-live API). The report covers engagement, themes, emotions,
risk flags, counsellor effectiveness, and cognitive profile.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from counselai.storage.models import SessionRecord, Turn
from counselai.storage.repositories.sessions import SessionRepository

logger = logging.getLogger(__name__)

REPORT_PROMPT = """You are a senior school counselling analyst reviewing a completed session
with an Indian student (class 9-12, age 14-18).

Analyze the transcript below and produce a JSON report with exactly these keys:

{
  "session_summary": "2-3 sentence overview of what happened. Plain language — a parent or teacher should understand it.",

  "student_engagement_score": 7,
  "student_engagement_rationale": "Brief explanation of why this score (1=disengaged, 10=highly active).",

  "key_themes": [
    {"theme": "string label", "evidence": "direct quote or moment from transcript"}
  ],

  "emotional_indicators": {
    "primary_emotion": "dominant emotion observed",
    "secondary_emotions": ["other emotions present"],
    "trajectory": "how emotions shifted during the session",
    "emotional_vocabulary_level": "limited | developing | articulate"
  },

  "risk_flags": {
    "level": "none | low | moderate | high | critical",
    "flags": ["specific concerning statements or patterns"],
    "protective_factors": ["strengths and supports identified"],
    "immediate_safety_concern": false
  },

  "counsellor_effectiveness": {
    "listen_phase": "Did the counsellor actively listen early on? Evidence.",
    "probe_phase": "Did they ask follow-up questions to go deeper? Evidence.",
    "dig_deeper_phase": "Did they help the student reach insight or self-reflection? Evidence.",
    "pattern_followed": true,
    "strengths": ["what the counsellor did well"],
    "areas_to_improve": ["where they could do better"]
  },

  "recommended_followups": {
    "actions": ["concrete next steps"],
    "topics_for_next_session": ["threads to pick up"],
    "referral_needed": false,
    "referral_type": "none | school_counsellor | psychologist | psychiatrist | helpline",
    "urgency": "routine | soon | urgent | immediate"
  },

  "cognitive_profile_snapshot": {
    "decision_making_style": "impulsive | avoidant | deliberate | dependent — with brief evidence",
    "emotional_regulation": "low | moderate | high — how well they manage emotions, with evidence",
    "social_awareness": "low | moderate | high — understanding of others' perspectives, with evidence",
    "self_awareness": "low | moderate | high — ability to reflect on own patterns",
    "coping_strategies": ["strategies they mentioned or demonstrated"]
  }
}

## Rules
- Base everything on the actual transcript. Don't invent things that weren't said.
- Quote the student directly when citing evidence.
- Risk flags are the most critical section. When in doubt, flag it.
- If the student mentioned self-harm, suicide, abuse, or substance use — risk level must be at least "moderate".
- Keep language jargon-free. Say "shows signs consistent with" not "has depression".
- For counsellor effectiveness, evaluate against the LISTEN > PROBE > DIG DEEPER pattern:
  * LISTEN: Did they let the student talk first? Did they reflect back?
  * PROBE: Did they ask open-ended questions? Did they explore what was said?
  * DIG DEEPER: Did they challenge gently? Did insights emerge?
- Cultural context matters — board exam pressure, coaching stress, family expectations, and
  Indian social dynamics should be considered when interpreting engagement and emotional state.
- recommended_followups.actions should be concrete, not vague "continue monitoring."

## Transcript
"""


@dataclass
class SessionReport:
    """Parsed report output."""

    session_summary: str = ""
    student_engagement_score: int = 0
    student_engagement_rationale: str = ""
    key_themes: list[dict[str, str]] = field(default_factory=list)
    emotional_indicators: dict[str, Any] = field(default_factory=dict)
    risk_flags: dict[str, Any] = field(default_factory=dict)
    counsellor_effectiveness: dict[str, Any] = field(default_factory=dict)
    recommended_followups: dict[str, Any] = field(default_factory=dict)
    cognitive_profile_snapshot: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_summary": self.session_summary,
            "student_engagement_score": self.student_engagement_score,
            "student_engagement_rationale": self.student_engagement_rationale,
            "key_themes": self.key_themes,
            "emotional_indicators": self.emotional_indicators,
            "risk_flags": self.risk_flags,
            "counsellor_effectiveness": self.counsellor_effectiveness,
            "recommended_followups": self.recommended_followups,
            "cognitive_profile_snapshot": self.cognitive_profile_snapshot,
        }


def _build_transcript(turns: list[Turn]) -> str:
    lines: list[str] = []
    for t in sorted(turns, key=lambda x: x.turn_index):
        speaker = t.speaker.upper() if isinstance(t.speaker, str) else str(t.speaker).upper()
        lines.append(f"[{speaker}] {t.text}")
    return "\n".join(lines)


def _parse_report_json(raw_text: str) -> SessionReport:
    text = raw_text.strip()
    if text.startswith("```"):
        first_nl = text.index("\n") if "\n" in text else len(text)
        text = text[first_nl + 1:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        logger.warning("Failed to parse report JSON from Gemini response")
        return SessionReport(
            session_summary="Report generation failed — could not parse LLM output.",
            raw={"_parse_error": True, "_raw": raw_text[:1000]},
        )

    return SessionReport(
        session_summary=data.get("session_summary", ""),
        student_engagement_score=data.get("student_engagement_score", 0),
        student_engagement_rationale=data.get("student_engagement_rationale", ""),
        key_themes=data.get("key_themes", []),
        emotional_indicators=data.get("emotional_indicators", {}),
        risk_flags=data.get("risk_flags", {}),
        counsellor_effectiveness=data.get("counsellor_effectiveness", {}),
        recommended_followups=data.get("recommended_followups", {}),
        cognitive_profile_snapshot=data.get("cognitive_profile_snapshot", {}),
        raw=data,
    )


async def generate_report(
    db: AsyncSession,
    session_id: uuid.UUID,
    *,
    api_key: str | None = None,
    force: bool = False,
) -> SessionReport:
    """Generate a post-session report for a completed session.

    If a report already exists in the DB and force=False, returns the cached version.
    Otherwise calls Gemini to generate a fresh report and stores it.
    """
    repo = SessionRepository(db)
    session = await repo.get(session_id)
    if session is None:
        raise ValueError(f"Session {session_id} not found")

    # Return cached report if available
    if not force and session.report:
        try:
            data = json.loads(session.report)
            return SessionReport(
                session_summary=data.get("session_summary", ""),
                student_engagement_score=data.get("student_engagement_score", 0),
                student_engagement_rationale=data.get("student_engagement_rationale", ""),
                key_themes=data.get("key_themes", []),
                emotional_indicators=data.get("emotional_indicators", {}),
                risk_flags=data.get("risk_flags", {}),
                counsellor_effectiveness=data.get("counsellor_effectiveness", {}),
                recommended_followups=data.get("recommended_followups", {}),
                cognitive_profile_snapshot=data.get("cognitive_profile_snapshot", {}),
                raw=data,
            )
        except (json.JSONDecodeError, AttributeError):
            pass  # regenerate if cached report is corrupted

    turns = await repo.get_turns(session_id)
    if not turns:
        logger.warning("Session %s has no turns — cannot generate report", session_id)
        return SessionReport(session_summary="No transcript available for this session.")

    transcript = _build_transcript(list(turns))
    prompt = REPORT_PROMPT + transcript

    # Call Gemini
    from google import genai
    from google.genai import types as gt

    key = api_key or os.environ.get("GEMINI_API_KEY", "")
    if not key:
        raise RuntimeError("GEMINI_API_KEY not set")

    client = genai.Client(api_key=key, http_options={"api_version": "v1beta"})
    response = client.models.generate_content(
        model="models/gemini-2.5-flash",
        contents=[prompt],
        config=gt.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.3,
        ),
    )
    raw_text = response.text or ""
    report = _parse_report_json(raw_text)

    # Store report JSON in DB
    session.report = json.dumps(report.to_dict(), default=str)
    await db.flush()

    logger.info(
        "Report generated for session %s: engagement=%d, risk=%s",
        session_id,
        report.student_engagement_score,
        report.risk_flags.get("level", "unknown"),
    )

    return report
