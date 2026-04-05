"""Unified post-session analysis — ONE Gemini call for all dashboard views.

Replaces the previous 4-module pipeline (face_analyzer + voice_analyzer +
profile_generator + report_generator) with a single structured-output call
to gemini-3.1-flash-lite-preview.

Input: session transcript (list of turns) + real-time observations + student context
Output: structured JSON matching ANALYSIS_SCHEMA — feeds all 3 dashboards
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from google import genai
from google.genai import types as gt

logger = logging.getLogger(__name__)

ANALYSIS_MODEL = "gemini-3.1-flash-lite-preview"

ANALYSIS_PROMPT = """\
You are an expert Indian school counsellor analyst. Analyze the following \
counselling session transcript and produce a comprehensive structured analysis.

The student is in classes 9-12 (ages 14-18) in the Indian education system.

Base EVERYTHING on what was actually said. Quote the student when citing evidence.
Risk assessment is the most critical section — when in doubt, err on caution.
Never diagnose — say "shows signs consistent with" not "has depression/anxiety."
Keep summaries in plain language a teacher or parent can understand.
Cultural context matters — what looks like low engagement may be a student taught \
not to share feelings with adults.

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
## Instructions for face_data and voice_data
Use the real-time observations above (if available) to populate the face_data and \
voice_data sections. If video was provided, also use visible facial cues. \
If no observations or video are available, provide your best assessment from \
transcript content alone (speech patterns, emotional language, etc.).\
"""

ANALYSIS_SCHEMA = {
    "type": "object",
    "properties": {
        "session_summary": {"type": "string"},
        "engagement_score": {"type": "integer"},
        "key_themes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "theme": {"type": "string"},
                    "evidence": {"type": "string"},
                    "severity": {"type": "string", "enum": ["low", "medium", "high"]},
                },
                "required": ["theme", "evidence", "severity"],
            },
        },
        "emotional_analysis": {
            "type": "object",
            "properties": {
                "primary_emotion": {"type": "string"},
                "secondary_emotions": {"type": "array", "items": {"type": "string"}},
                "trajectory": {"type": "string"},
                "emotional_vocabulary": {"type": "string", "enum": ["limited", "developing", "articulate"]},
            },
            "required": ["primary_emotion", "trajectory", "emotional_vocabulary"],
        },
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
        "constructs": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "key": {"type": "string"},
                    "label": {"type": "string"},
                    "score": {"type": "number"},
                    "status": {"type": "string", "enum": ["supported", "mixed", "weak"]},
                    "evidence_summary": {"type": "string"},
                },
                "required": ["key", "label", "score", "status", "evidence_summary"],
            },
        },
        "personality_snapshot": {
            "type": "object",
            "properties": {
                "traits": {"type": "array", "items": {"type": "string"}},
                "communication_style": {"type": "string"},
                "decision_making": {"type": "string"},
            },
            "required": ["traits", "communication_style", "decision_making"],
        },
        "cognitive_profile": {
            "type": "object",
            "properties": {
                "critical_thinking": {"type": "integer"},
                "perspective_taking": {"type": "integer"},
                "moral_reasoning_stage": {"type": "string"},
                "problem_solving_style": {"type": "string"},
            },
            "required": ["critical_thinking", "perspective_taking"],
        },
        "emotional_profile": {
            "type": "object",
            "properties": {
                "eq_score": {"type": "integer"},
                "empathy_level": {"type": "string"},
                "stress_response": {"type": "string"},
                "anxiety_markers": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["eq_score", "empathy_level", "stress_response"],
        },
        "behavioral_insights": {
            "type": "object",
            "properties": {
                "confidence": {"type": "integer"},
                "leadership_potential": {"type": "string"},
                "peer_influence": {"type": "string"},
                "academic_pressure": {"type": "string"},
                "resilience": {"type": "string"},
                "coping_strategies": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["confidence", "resilience"],
        },
        "key_moments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "quote": {"type": "string"},
                    "insight": {"type": "string"},
                },
                "required": ["quote", "insight"],
            },
        },
        "student_view": {
            "type": "object",
            "properties": {
                "strengths": {"type": "array", "items": {"type": "string"}},
                "interests": {"type": "array", "items": {"type": "string"}},
                "growth_areas": {"type": "array", "items": {"type": "string"}},
                "encouragement": {"type": "string"},
                "next_steps": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["strengths", "growth_areas", "encouragement"],
        },
        "school_view": {
            "type": "object",
            "properties": {
                "themes": {"type": "array", "items": {"type": "string"}},
                "academic_pressure_level": {"type": "string", "enum": ["none", "mild", "moderate", "severe"]},
                "family_dynamics_concern": {"type": "string", "enum": ["none", "mild", "moderate", "severe"]},
                "peer_relationship_issues": {"type": "string", "enum": ["none", "mild", "moderate", "severe"]},
                "career_confusion": {"type": "string", "enum": ["none", "mild", "moderate", "severe"]},
            },
            "required": ["themes", "academic_pressure_level"],
        },
        "follow_up": {
            "type": "object",
            "properties": {
                "actions": {"type": "array", "items": {"type": "string"}},
                "topics_for_next_session": {"type": "array", "items": {"type": "string"}},
                "referral_needed": {"type": "boolean"},
                "referral_type": {"type": "string"},
                "urgency": {"type": "string", "enum": ["routine", "soon", "urgent", "immediate"]},
            },
            "required": ["actions", "referral_needed", "urgency"],
        },
        "red_flags": {"type": "array", "items": {"type": "string"}},
        "recommendations": {"type": "array", "items": {"type": "string"}},
        # Face and voice analysis — populated from real-time observations + video
        "face_data": {
            "type": "object",
            "properties": {
                "dominant_emotion": {"type": "string"},
                "emotion_trajectory": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "point": {"type": "string"},
                            "emotion": {"type": "string"},
                        },
                        "required": ["point", "emotion"],
                    },
                },
                "engagement_indicators": {"type": "string"},
                "notable_expressions": {"type": "array", "items": {"type": "string"}},
                "eye_contact_score": {"type": "integer"},
                "facial_tension_score": {"type": "integer"},
                "emotion_stability": {"type": "string"},
            },
            "required": ["dominant_emotion", "engagement_indicators"],
        },
        "voice_data": {
            "type": "object",
            "properties": {
                "speech_patterns": {"type": "string"},
                "confidence_level": {"type": "string"},
                "hesitation_markers": {"type": "array", "items": {"type": "string"}},
                "emotional_tone_shifts": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "point": {"type": "string"},
                            "shift": {"type": "string"},
                        },
                        "required": ["point", "shift"],
                    },
                },
                "overall_confidence_score": {"type": "integer"},
                "speech_rate": {"type": "string"},
                "volume_pattern": {"type": "string"},
            },
            "required": ["speech_patterns", "confidence_level"],
        },
        # Per-segment analysis (maps to case study parts)
        "segment_analysis": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "segment_name": {"type": "string"},
                    "content_summary": {"type": "string"},
                    "emotional_state": {"type": "string"},
                    "audio_signals": {"type": "string"},
                    "video_signals": {"type": "string"},
                    "key_insight": {"type": "string"},
                },
                "required": ["segment_name", "content_summary", "emotional_state"],
            },
        },
    },
    "required": [
        "session_summary", "engagement_score", "key_themes",
        "emotional_analysis", "risk_assessment", "constructs",
        "personality_snapshot", "cognitive_profile", "emotional_profile",
        "behavioral_insights", "key_moments",
        "student_view", "school_view", "follow_up",
        "red_flags", "recommendations",
        "face_data", "voice_data", "segment_analysis",
    ],
}


def _build_transcript_text(transcript_data: list[dict]) -> str:
    """Format transcript turns into readable text."""
    lines = []
    for entry in transcript_data:
        role = entry.get("role", "unknown").upper()
        text = entry.get("text", "").strip()
        if text:
            lines.append(f"[{role}] {text}")
    return "\n".join(lines) if lines else "(No transcript available)"


def _build_observations_section(observations: list[dict]) -> str:
    """Format real-time observations into analysis context."""
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
    """Format segment transitions into analysis context."""
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
    """Run unified post-session analysis with a single multimodal Gemini call.

    Accepts transcript + optional video + real-time observations.
    When observations are provided, they give temporal per-turn context
    for face/voice/emotional analysis that pure transcript misses.

    Returns the full structured analysis JSON, or a minimal fallback on failure.
    """
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise EnvironmentError("GEMINI_API_KEY is not set")

    client = genai.Client(api_key=api_key)

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

    # Build multimodal contents: text prompt + optional video
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

    try:
        response = client.models.generate_content(
            model=ANALYSIS_MODEL,
            contents=contents,
            config=gt.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=ANALYSIS_SCHEMA,
                temperature=0.3,
                max_output_tokens=6000,
            ),
        )
        raw = (response.text or "").strip()
        result = json.loads(raw)
        logger.info(
            "Unified analysis complete: risk=%s, themes=%d, observations=%d, segments=%d",
            result.get("risk_assessment", {}).get("level", "?"),
            len(result.get("key_themes", [])),
            obs_count,
            seg_count,
        )
        return result
    except Exception as exc:
        logger.error("Unified analysis failed: %s", exc, exc_info=True)
        return _fallback_result(str(exc))


def _fallback_result(error_msg: str = "") -> dict[str, Any]:
    """Minimal valid result when Gemini call fails."""
    return {
        "session_summary": "Analysis could not be completed." + (f" Error: {error_msg}" if error_msg else ""),
        "engagement_score": 0,
        "key_themes": [],
        "emotional_analysis": {
            "primary_emotion": "unknown",
            "secondary_emotions": [],
            "trajectory": "Unable to determine",
            "emotional_vocabulary": "limited",
        },
        "risk_assessment": {
            "level": "none",
            "flags": [],
            "protective_factors": [],
            "immediate_safety_concern": False,
        },
        "constructs": [],
        "personality_snapshot": {"traits": [], "communication_style": "", "decision_making": ""},
        "cognitive_profile": {"critical_thinking": 0, "perspective_taking": 0},
        "emotional_profile": {"eq_score": 0, "empathy_level": "", "stress_response": ""},
        "behavioral_insights": {"confidence": 0, "resilience": ""},
        "key_moments": [],
        "student_view": {"strengths": [], "growth_areas": [], "encouragement": "", "interests": [], "next_steps": []},
        "school_view": {"themes": [], "academic_pressure_level": "none"},
        "follow_up": {"actions": [], "referral_needed": False, "urgency": "routine"},
        "red_flags": [],
        "recommendations": [],
        "face_data": {"dominant_emotion": "unknown", "engagement_indicators": "Not analyzed"},
        "voice_data": {"speech_patterns": "unknown", "confidence_level": "Not analyzed"},
        "segment_analysis": [],
    }
