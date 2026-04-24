"""Unified post-session analysis — ONE Gemini call producing 9-dimension report.

Replaces the previous flat analysis with a structured 9-dimension scoring system
based on the CounselAI Report Engine rubrics. The single call produces:
- 9 dimension scores with evidence
- 4-5 key moments
- Counsellor snapshot
- Risk assessment
- Next session recommendation
- Student / school / follow-up views
"""

from __future__ import annotations

import json
import logging
from typing import Any

from google.genai import types as gt

from counselai.api.gemini_client import get_gemini_client, GEMINI_ANALYSIS_MODEL

logger = logging.getLogger(__name__)

ANALYSIS_PROMPT = """\
You are an expert educational psychologist and Indian school counsellor analyst. \
Analyze the following counselling session transcript and produce a comprehensive \
structured analysis scoring the student on 9 behavioural dimensions.

The student is in classes 9-12 (ages 14-18) in the Indian education system.

## RULES
- Base EVERYTHING on what was actually said. Quote the student when citing evidence.
- Risk assessment is the most critical section — when in doubt, err on caution.
- Dimension scores are integers 1-10. Do NOT inflate scores to be kind.
- Key moment quotes must be EXACT from the transcript — do not paraphrase.
- Growth tips must be SPECIFIC to this student, not generic advice.
- Never diagnose — say "shows signs consistent with" not "has depression/anxiety."
- Cultural context matters — what looks like low engagement may be cultural.

## SCORING RUBRICS FOR 9 DIMENSIONS

### DOMAIN: THINKING

**1. Analytical Depth** — Can they decompose a complex situation into constituent factors?
- Emerging (1-3): Restates problem as given; single-factor thinking
- Developing (4-6): Identifies 2-3 factors; applies a concept
- Proficient (7-8): Identifies most factors; reasons with trade-offs
- Advanced (9-10): Connects to systemic patterns; identifies non-obvious factors

**2. Critical Reasoning** — Do they question assumptions and demand evidence?
- Emerging (1-3): Accepts scenario at face value; no counter-arguments
- Developing (4-6): Questions one assumption OR raises one counter-argument
- Proficient (7-8): Challenges 2+ assumptions; supports claims with evidence
- Advanced (9-10): Systematically tests assumptions; evaluates evidence quality

**3. Decision Reasoning** — Can they commit to a justified position under ambiguity?
- Emerging (1-3): Avoids choosing; "I don't know" without reasoning
- Developing (4-6): Chooses but can't articulate why; OR articulates but won't commit
- Proficient (7-8): Clear position + stated reasoning + 1-2 trade-offs acknowledged
- Advanced (9-10): Multi-layered reasoning + trade-offs + conditions for changing mind

### DOMAIN: CHARACTER

**4. Perspective & Empathy** — Can they authentically see through multiple stakeholders' eyes?
- Emerging (1-3): Single perspective; doesn't consider others
- Developing (4-6): Mentions others exist but surface-level
- Proficient (7-8): Inhabits 2-3 perspectives with emotional depth
- Advanced (9-10): Holds contradictory perspectives; identifies hidden stakeholders

**5. Ethical Compass** — What BASIS drives their moral reasoning?
- Emerging (1-3): Consequence-based (punishment/reward)
- Developing (4-6): Rule-based (authority/norms)
- Proficient (7-8): Principle-based (values/trust/fairness)
- Advanced (9-10): Principle-based with nuance (conflicting principles weighed)

**6. Self-Reflection** — Do they think about their OWN thinking?
- Emerging (1-3): No metacognitive statements; no acknowledged uncertainty
- Developing (4-6): Occasional "I'm not sure" without follow-through
- Proficient (7-8): Explicit metacognition ("I initially thought X, but...")
- Advanced (9-10): Actively seeks disconfirmation; articulates learning

**7. Resilience & Adaptability** — When challenged, do they crumble, rigidify, or adapt?
- Emerging (1-3): Immediately abandons position; agrees with everything
- Developing (4-6): Gets defensive OR rigid; won't engage with new info
- Proficient (7-8): Engages with challenge; modifies reasoning; recovers confidence
- Advanced (9-10): Thrives on challenge; uses pushback as fuel for deeper thinking

### DOMAIN: EXPRESSION

**8. Communication & Presence** — Are ideas expressed clearly AND with conviction?
- Emerging (1-3): Unclear ideas; excessive fillers; flat delivery
- Developing (4-6): Clear in parts; loses coherence under complexity
- Proficient (7-8): Clear logical flow; controlled pace; minimal fillers
- Advanced (9-10): Compelling clarity; ideas build naturally; conviction throughout

**9. Engagement & Curiosity** — Were they genuinely invested and exploring?
- Emerging (1-3): Minimal responses; waits for prompts; no curiosity
- Developing (4-6): Responds adequately but doesn't elaborate; no questions
- Proficient (7-8): Elaborates without prompting; asks 1-2 questions; sustained focus
- Advanced (9-10): Drives conversation; probing questions; delight in complexity

## Transcript
{transcript}

## Student Context
Name: {student_name}
Grade: {student_grade}
School: {student_school}
Case study: {case_study}
Session duration: {duration_seconds}s
{observations_section}
{segments_section}
## KEY MOMENTS
Identify 4-5 pivotal moments where the student showed a cognitive/emotional shift, \
demonstrated a strength or weakness, changed position, showed empathy, or responded \
to a challenge. Quotes must be EXACT from the transcript.

## COUNSELLOR SNAPSHOT
Write 2-3 sentences: dominant moral reasoning pattern, engagement level, \
notable confidence shifts, resilience pattern (crumble/rigidify/adapt/thrive), \
risk flag status. Clinical and signal-rich.

## NEXT SESSION
Recommend the next case study category + difficulty based on strengths/growth areas.\
"""

ANALYSIS_SCHEMA = {
    "type": "object",
    "properties": {
        "dimensions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "domain": {"type": "string"},
                    "score": {"type": "integer", "minimum": 1, "maximum": 10},
                    "because": {"type": "string"},
                    "key_moment_quote": {"type": "string"},
                    "key_moment_turn": {"type": "integer"},
                    "growth_tip": {"type": "string"},
                    "evidence_sources": {
                        "type": "array",
                        "items": {"type": "boolean"},
                    },
                },
                "required": ["name", "domain", "score", "because", "key_moment_quote", "key_moment_turn", "growth_tip"],
            },
        },
        "key_moments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "turn": {"type": "integer"},
                    "quote": {"type": "string"},
                    "audio_signal": {"type": "string"},
                    "dims": {"type": "array", "items": {"type": "integer"}},
                    "insight": {"type": "string"},
                },
                "required": ["turn", "quote", "insight"],
            },
        },
        "snapshot": {"type": "string"},
        "risk_assessment": {
            "type": "object",
            "properties": {
                "level": {"type": "string", "enum": ["none", "low", "moderate", "high", "critical"]},
                "flags": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "key": {"type": "string"},
                            "severity": {"type": "string", "enum": ["low", "medium", "high", "critical"]},
                            "reason": {"type": "string"},
                        },
                        "required": ["key", "severity", "reason"],
                    },
                },
                "protective_factors": {"type": "array", "items": {"type": "string"}},
                "immediate_safety_concern": {"type": "boolean"},
            },
            "required": ["level", "flags", "protective_factors", "immediate_safety_concern"],
        },
        "next_session_rec": {"type": "string"},
        "session_summary": {"type": "string"},
        "student_view": {
            "type": "object",
            "properties": {
                "strengths": {"type": "array", "items": {"type": "string"}},
                "growth_areas": {"type": "array", "items": {"type": "string"}},
                "encouragement": {"type": "string"},
            },
            "required": ["strengths", "growth_areas", "encouragement"],
        },
        "follow_up": {
            "type": "object",
            "properties": {
                "actions": {"type": "array", "items": {"type": "string"}},
                "topics_for_next_session": {"type": "array", "items": {"type": "string"}},
                "referral_needed": {"type": "boolean"},
                "urgency": {"type": "string", "enum": ["routine", "soon", "urgent", "immediate"]},
            },
            "required": ["actions", "referral_needed", "urgency"],
        },
    },
    "required": [
        "dimensions", "key_moments", "snapshot", "risk_assessment",
        "next_session_rec", "session_summary", "student_view", "follow_up",
    ],
}


def _build_transcript_text(transcript_data: list[dict]) -> str:
    """Format transcript turns into readable text with turn numbers."""
    lines = []
    for i, entry in enumerate(transcript_data, 1):
        role = entry.get("role", "unknown").upper()
        text = entry.get("text", "").strip()
        if text:
            lines.append(f"[Turn {i} | {role}] {text}")
    return "\n".join(lines) if lines else "(No transcript available)"


def _build_observations_section(observations: list[dict]) -> str:
    if not observations:
        return ""
    lines = ["## Real-Time Observations (captured during session via audio/video analysis)"]
    for i, obs in enumerate(observations, 1):
        lines.append(
            f"{i}. [{obs.get('modality', '?')}] {obs.get('observation_type', '?')}: "
            f"{obs.get('emotion', '?')} (confidence: {obs.get('confidence', 0):.0%}) — "
            f"{obs.get('description', '')} (turn {obs.get('turn_number', '?')})"
        )
    return "\n".join(lines) + "\n"


def _build_segments_section(segments: list[dict]) -> str:
    if not segments:
        return ""
    lines = ["## Session Segments (topic transitions detected during session)"]
    for i, seg in enumerate(segments, 1):
        lines.append(
            f"{i}. \"{seg.get('segment_name', '?')}\" — {seg.get('reason', '')} (turn {seg.get('turn_number', '?')})"
        )
    return "\n".join(lines) + "\n"


def analyze_session(
    transcript_data: list[dict],
    *,
    student_name: str = "Student",
    student_grade: str = "10",
    student_school: str = "",
    case_study: str = "",
    duration_seconds: int = 0,
    video_bytes: bytes | None = None,
    observations: list[dict] | None = None,
    segments: list[dict] | None = None,
) -> dict[str, Any]:
    """Run unified post-session analysis with a single Gemini call.

    Returns the full structured analysis JSON with 9 dimensions, key moments,
    snapshot, risk assessment, and recommendations.
    """
    client = get_gemini_client()

    transcript_text = _build_transcript_text(transcript_data)
    observations_section = _build_observations_section(observations or [])
    segments_section = _build_segments_section(segments or [])

    prompt = ANALYSIS_PROMPT.format(
        transcript=transcript_text,
        student_name=student_name,
        student_grade=student_grade,
        student_school=student_school,
        case_study=case_study or "(none)",
        duration_seconds=duration_seconds,
        observations_section=observations_section,
        segments_section=segments_section,
    )

    contents: list = [prompt]
    if video_bytes and len(video_bytes) > 1000:
        contents.append(
            gt.Part.from_bytes(data=video_bytes, mime_type="video/webm")
        )
        logger.info("Including video (%d bytes) in multimodal analysis call", len(video_bytes))

    obs_count = len(observations or [])
    seg_count = len(segments or [])
    if obs_count or seg_count:
        logger.info("Including %d observations and %d segments in analysis", obs_count, seg_count)

    raw: str | None = None
    try:
        response = client.models.generate_content(
            model=GEMINI_ANALYSIS_MODEL,
            contents=contents,
            config=gt.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=ANALYSIS_SCHEMA,
                temperature=0.3,
                max_output_tokens=8000,
            ),
        )
        raw = (response.text or "").strip()
        result = json.loads(raw)
        logger.info(
            "Unified analysis complete via %s: risk=%s, dimensions=%d, moments=%d",
            GEMINI_ANALYSIS_MODEL,
            result.get("risk_assessment", {}).get("level", "?"),
            len(result.get("dimensions", [])),
            len(result.get("key_moments", [])),
        )
        try:
            um = response.usage_metadata
            result["_analysis_usage"] = {
                "input_tokens": int(getattr(um, "prompt_token_count", 0) or 0),
                "output_tokens": int(getattr(um, "candidates_token_count", 0) or 0),
            }
        except Exception:
            pass
        return result
    except Exception as exc:
        logger.error("Unified analysis failed: %s", exc, exc_info=True)
        return _fallback_result(str(exc), raw_output=raw)


def _fallback_result(error_msg: str = "", *, raw_output: str | None = None) -> dict[str, Any]:
    """Well-formed skeleton matching ANALYSIS_SCHEMA when the Gemini call fails."""
    logger.warning(
        "Unified analysis falling back to skeleton result. error=%r raw_output=%r",
        error_msg,
        (raw_output[:500] + "...") if raw_output and len(raw_output) > 500 else raw_output,
    )

    summary = "Analysis could not be completed." + (f" Error: {error_msg}" if error_msg else "")

    dim_names = [
        ("Analytical Depth", "Thinking"),
        ("Critical Reasoning", "Thinking"),
        ("Decision Reasoning", "Thinking"),
        ("Perspective & Empathy", "Character"),
        ("Ethical Compass", "Character"),
        ("Self-Reflection", "Character"),
        ("Resilience & Adaptability", "Character"),
        ("Communication & Presence", "Expression"),
        ("Engagement & Curiosity", "Expression"),
    ]

    return {
        "dimensions": [
            {
                "name": name,
                "domain": domain,
                "score": 1,
                "because": "Fallback — no analysis produced.",
                "key_moment_quote": "",
                "key_moment_turn": 0,
                "growth_tip": "",
                "evidence_sources": [False, False, False],
            }
            for name, domain in dim_names
        ],
        "key_moments": [],
        "snapshot": summary,
        "risk_assessment": {
            "level": "none",
            "flags": [],
            "protective_factors": [],
            "immediate_safety_concern": False,
        },
        "next_session_rec": "",
        "session_summary": summary,
        "student_view": {
            "strengths": [],
            "growth_areas": [],
            "encouragement": "",
        },
        "follow_up": {
            "actions": [],
            "topics_for_next_session": [],
            "referral_needed": False,
            "urgency": "routine",
        },
    }
