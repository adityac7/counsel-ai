"""Post-session analysis — extract themes, emotional state, risk flags.

Uses the structured prompt from counselai.prompts.post_session to produce
a JSON analysis of a completed session, then stores results back into the
SessionRecord.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from counselai.prompts.post_session import POST_SESSION_ANALYSIS_PROMPT
from counselai.storage.models import SessionRecord, Turn
from counselai.storage.repositories.sessions import SessionRepository

logger = logging.getLogger(__name__)


@dataclass
class AnalysisResult:
    """Parsed output of the post-session LLM analysis."""

    key_themes: list[dict[str, Any]] = field(default_factory=list)
    emotional_state: dict[str, Any] = field(default_factory=dict)
    behavioural_observations: dict[str, Any] = field(default_factory=dict)
    risk_assessment: dict[str, Any] = field(default_factory=dict)
    indian_context_factors: dict[str, Any] = field(default_factory=dict)
    follow_up: dict[str, Any] = field(default_factory=dict)
    session_quality: dict[str, Any] = field(default_factory=dict)
    raw_json: dict[str, Any] = field(default_factory=dict)

    @property
    def risk_level(self) -> str | None:
        return self.risk_assessment.get("risk_level")

    @property
    def follow_up_needed(self) -> bool:
        urgency = self.follow_up.get("urgency", "routine")
        return urgency in ("soon", "urgent", "immediate") or self.follow_up.get("referral_needed", False)

    @property
    def topics(self) -> list[str]:
        return [t.get("theme", "") for t in self.key_themes if t.get("theme")]

    @property
    def summary(self) -> str | None:
        return self.session_quality.get("session_summary")

    @property
    def mood_start(self) -> str | None:
        trajectory = self.emotional_state.get("emotional_trajectory", "")
        primary = self.emotional_state.get("primary_emotion")
        # Best effort — the trajectory string often starts with initial state
        if trajectory and trajectory.lower().startswith("started"):
            first_word = trajectory.split(",")[0].replace("Started ", "").strip()
            if first_word:
                return first_word
        return primary

    @property
    def mood_end(self) -> str | None:
        trajectory = self.emotional_state.get("emotional_trajectory", "")
        if "by end" in trajectory.lower() or "ended" in trajectory.lower():
            # Grab the last clause
            parts = trajectory.rsplit(",", 1)
            if len(parts) > 1:
                return parts[-1].strip().rstrip(".")
        return self.emotional_state.get("primary_emotion")


def _build_transcript_text(turns: list[Turn]) -> str:
    """Format turns into a readable transcript string."""
    lines: list[str] = []
    for t in sorted(turns, key=lambda x: x.turn_index):
        speaker = t.speaker.upper() if isinstance(t.speaker, str) else str(t.speaker).upper()
        lines.append(f"[{speaker}] {t.text}")
    return "\n".join(lines)


def parse_analysis_json(raw_text: str) -> AnalysisResult:
    """Parse the LLM's JSON response into an AnalysisResult.

    Handles markdown code fences and partial JSON gracefully.
    """
    text = raw_text.strip()
    # Strip markdown code fence if present
    if text.startswith("```"):
        # Remove opening fence (```json or ```)
        first_newline = text.index("\n") if "\n" in text else len(text)
        text = text[first_newline + 1 :]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        logger.warning("Failed to parse analysis JSON, returning empty result")
        return AnalysisResult(raw_json={"_parse_error": True, "_raw": raw_text[:500]})

    return AnalysisResult(
        key_themes=data.get("key_themes", []),
        emotional_state=data.get("emotional_state", {}),
        behavioural_observations=data.get("behavioural_observations", {}),
        risk_assessment=data.get("risk_assessment", {}),
        indian_context_factors=data.get("indian_context_factors", {}),
        follow_up=data.get("follow_up", {}),
        session_quality=data.get("session_quality", {}),
        raw_json=data,
    )


async def analyze_session(
    db: AsyncSession,
    session_id: uuid.UUID,
    *,
    llm_callable: Any | None = None,
) -> AnalysisResult:
    """Run post-session analysis on a completed session.

    Args:
        db: Async database session.
        session_id: The session to analyze.
        llm_callable: An async callable ``f(prompt: str) -> str`` that calls
            the LLM. If None, builds the prompt and transcript but skips
            the LLM call (useful for testing the pipeline).

    Returns:
        AnalysisResult with extracted themes, risk, etc.
        Also persists key fields back to SessionRecord.
    """
    repo = SessionRepository(db)
    session = await repo.get(session_id)
    if session is None:
        raise ValueError(f"Session {session_id} not found")

    turns = await repo.get_turns(session_id)
    if not turns:
        logger.warning("Session %s has no turns — skipping analysis", session_id)
        return AnalysisResult()

    transcript_text = _build_transcript_text(list(turns))
    prompt = POST_SESSION_ANALYSIS_PROMPT + "\n" + transcript_text

    # Call the LLM
    if llm_callable is not None:
        raw_response = await llm_callable(prompt)
        result = parse_analysis_json(raw_response)
    else:
        logger.info("No LLM callable provided — returning empty analysis for session %s", session_id)
        result = AnalysisResult()

    # Persist back to SessionRecord
    turn_count = len(turns)
    await repo.update_analysis(
        session_id,
        session_summary=result.summary,
        risk_level=result.risk_level,
        follow_up_needed=result.follow_up_needed,
        topics_discussed=result.topics if result.topics else None,
        student_mood_start=result.mood_start,
        student_mood_end=result.mood_end,
        turn_count=turn_count,
    )

    logger.info(
        "Session %s analyzed: risk=%s, themes=%d, follow_up=%s",
        session_id,
        result.risk_level,
        len(result.key_themes),
        result.follow_up_needed,
    )

    return result


async def analyze_session_with_gemini(
    db: AsyncSession,
    session_id: uuid.UUID,
    *,
    api_key: str | None = None,
) -> AnalysisResult:
    """Convenience wrapper that uses Gemini as the LLM backend.

    Imports google.genai lazily to avoid hard dependency for tests.
    """
    import os

    from google import genai
    from google.genai import types as gt

    key = api_key or os.environ.get("GEMINI_API_KEY", "")
    if not key:
        raise RuntimeError("GEMINI_API_KEY not set")

    client = genai.Client(api_key=key, http_options={"api_version": "v1beta"})

    async def _call_gemini(prompt: str) -> str:
        response = client.models.generate_content(
            model="models/gemini-2.5-flash",
            contents=[prompt],
            config=gt.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.3,
            ),
        )
        return response.text or ""

    return await analyze_session(db, session_id, llm_callable=_call_gemini)
