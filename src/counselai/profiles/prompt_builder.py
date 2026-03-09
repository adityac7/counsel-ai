"""Prompt construction for profile synthesis LLM calls.

Builds system and user prompts from evidence graphs, signal features,
and transcript data. Separate prompts for student, counsellor, and
school profile views to keep each focused and bounded.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from counselai.profiles.schemas import (
    CounsellorProfileView,
    SchoolProfileView,
    SessionProfile,
    StudentProfileView,
)

# ---------------------------------------------------------------------------
# JSON output schemas (passed to LLM for structured generation)
# ---------------------------------------------------------------------------

COUNSELLOR_VIEW_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "constructs": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "key": {"type": "string"},
                    "label": {"type": "string"},
                    "status": {"type": "string", "enum": ["supported", "mixed", "weak"]},
                    "score": {"type": "number", "minimum": 0, "maximum": 1},
                    "evidence_summary": {"type": "string"},
                    "evidence_refs": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "ref_type": {"type": "string"},
                                "ref_id": {"type": "string"},
                                "modality": {"type": "string"},
                                "summary": {"type": "string"},
                                "confidence": {"type": "number"},
                            },
                            "required": ["ref_type", "ref_id"],
                        },
                    },
                    "supporting_quotes": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": ["key", "label", "status", "evidence_summary"],
            },
        },
        "red_flags": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "key": {"type": "string"},
                    "severity": {"type": "string", "enum": ["low", "medium", "high"]},
                    "reason": {"type": "string"},
                    "evidence_refs": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "ref_type": {"type": "string"},
                                "ref_id": {"type": "string"},
                                "modality": {"type": "string"},
                                "summary": {"type": "string"},
                                "confidence": {"type": "number"},
                            },
                            "required": ["ref_type", "ref_id"],
                        },
                    },
                    "recommended_action": {"type": "string"},
                },
                "required": ["key", "severity", "reason"],
            },
        },
        "cross_modal_notes": {
            "type": "array",
            "items": {"type": "string"},
        },
        "recommended_follow_ups": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
    "required": ["summary", "constructs", "red_flags"],
}

STUDENT_VIEW_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "strengths": {"type": "array", "items": {"type": "string"}},
        "interests": {"type": "array", "items": {"type": "string"}},
        "growth_areas": {"type": "array", "items": {"type": "string"}},
        "suggested_next_steps": {"type": "array", "items": {"type": "string"}},
        "summary": {"type": "string"},
        "encouragement": {"type": "string"},
    },
    "required": ["strengths", "interests", "summary", "encouragement"],
}

SCHOOL_VIEW_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "primary_topics": {"type": "array", "items": {"type": "string"}},
        "risk_level": {"type": "string", "enum": ["low", "medium", "high"]},
        "engagement_rating": {"type": "string", "enum": ["low", "moderate", "high"]},
        "summary": {"type": "string"},
    },
    "required": ["primary_topics", "summary"],
}


# ---------------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------------

_COUNSELLOR_SYSTEM = """\
You are an expert school counsellor profile synthesizer for Indian students (classes 9-12).

Your job: synthesize a structured counsellor profile from multi-modal evidence — transcript \
content analysis, audio signal features (pauses, pitch, dysfluency), video signal features \
(gaze, engagement, tension), and cross-modal correlations.

RULES:
- Every construct MUST link back to specific evidence references (turn numbers, topic windows, signal observations).
- Use the evidence graph to identify supported vs contradicted hypotheses.
- Do NOT invent evidence. If a modality has low reliability, note it explicitly.
- Quote the student directly when relevant (use exact text from the transcript).
- Red flags must be grounded in observable patterns, not speculation.
- Cross-modal notes should highlight where audio/video signals agree or disagree with verbal content.
- Be balanced and evidence-based. Avoid clinical diagnosis.
- Keep the summary concise (2-4 sentences).
- Assess 4-8 constructs relevant to this student based on the evidence.

Common constructs to consider (select what's relevant):
- career_identity_clarity, self_awareness, emotional_regulation, decision_autonomy
- peer_influence_susceptibility, academic_motivation, family_pressure_response
- communication_confidence, critical_thinking, resilience, empathy_capacity
- value_clarity, conflict_resolution, stress_coping, future_orientation

Return valid JSON matching the specified schema. No markdown, no commentary outside the JSON."""

_STUDENT_SYSTEM = """\
You are writing a supportive, encouraging student-facing profile summary.

RULES:
- Language must be simple, warm, and non-diagnostic. No clinical terms.
- Focus on strengths, interests, and growth areas.
- Frame growth areas as opportunities, not weaknesses.
- Suggested next steps should be actionable and age-appropriate.
- The encouragement message should be genuine and specific to this student.
- Do NOT mention red flags, risk scores, or concerns.
- Do NOT reveal analysis methodology or mention "evidence graphs" or "signals".
- Keep it conversational — this is for a 14-18 year old Indian student.

Return valid JSON matching the specified schema. No markdown, no commentary outside the JSON."""

_SCHOOL_SYSTEM = """\
You are summarizing a counselling session for school administrators.

RULES:
- This is an AGGREGATE-SAFE summary. No individual clinical detail.
- Primary topics: list the main themes discussed (e.g. "career confusion", "peer pressure").
- Risk level: overall assessment based on red flag severity (low/medium/high).
- Engagement rating: based on session participation (low/moderate/high).
- Summary: 1-2 sentences, factual, non-clinical.
- Do NOT include student quotes, specific behavioral observations, or names.
- Do NOT include counsellor recommendations (those are for the counsellor view).

Return valid JSON matching the specified schema. No markdown, no commentary outside the JSON."""


# ---------------------------------------------------------------------------
# Evidence context formatting
# ---------------------------------------------------------------------------

def _format_transcript_summary(turns: list[dict]) -> str:
    """Format turns into a readable transcript excerpt."""
    if not turns:
        return "No transcript available."

    lines: list[str] = []
    for t in turns[:30]:  # Cap at 30 turns to stay within context
        speaker = t.get("speaker", "unknown").upper()
        text = t.get("text", "")
        idx = t.get("turn_index", "?")
        lines.append(f"[Turn {idx}] {speaker}: {text}")

    return "\n".join(lines)


def _format_evidence_context(
    content_features: dict | None,
    audio_features: dict | None,
    video_features: dict | None,
    evidence_graph: dict | None,
    topic_windows: list[dict] | None,
) -> str:
    """Assemble the evidence context block for the LLM prompt."""
    sections: list[str] = []

    # Content features summary
    if content_features:
        cf = content_features
        topics = cf.get("topics", [])
        if topics:
            topic_lines = []
            for t in topics:
                topic_lines.append(
                    f"  - {t.get('label', t.get('topic_key', '?'))}: "
                    f"depth={t.get('depth', '?')}, "
                    f"confidence={t.get('confidence', 0):.2f}, "
                    f"turns={t.get('turn_indices', [])}"
                )
            sections.append("CONTENT TOPICS:\n" + "\n".join(topic_lines))

        hedging = cf.get("hedging_markers", [])
        if hedging:
            h_lines = [
                f"  - Turn {h['turn_index']}: \"{h['text']}\" ({h.get('hedge_type', 'general')})"
                for h in hedging[:10]
            ]
            sections.append(f"HEDGING MARKERS ({len(hedging)} total):\n" + "\n".join(h_lines))

        agency = cf.get("agency_markers", [])
        if agency:
            a_lines = [
                f"  - Turn {a['turn_index']}: \"{a['text']}\" (level={a.get('level', '?')})"
                for a in agency[:10]
            ]
            sections.append(f"AGENCY MARKERS ({len(agency)} total):\n" + "\n".join(a_lines))

        avoidance = cf.get("avoidance_events", [])
        if avoidance:
            av_lines = [
                f"  - Turn {av['turn_index']}: avoided topic '{av.get('topic_key', '?')}' — \"{av.get('avoidance_text', '')}\""
                for av in avoidance[:10]
            ]
            sections.append(f"AVOIDANCE EVENTS ({len(avoidance)} total):\n" + "\n".join(av_lines))

        code_switch = cf.get("code_switch_events", [])
        if code_switch:
            cs_lines = [
                f"  - Turn {cs['turn_index']}: {cs.get('direction', '?')} — context: {cs.get('trigger_context', '?')}"
                for cs in code_switch[:10]
            ]
            sections.append(f"CODE-SWITCHING ({len(code_switch)} total):\n" + "\n".join(cs_lines))

        sections.append(
            f"CONTENT RELIABILITY: {cf.get('reliability_score', 0):.2f} | "
            f"Overall depth: {cf.get('overall_depth', '?')} | "
            f"Overall agency: {cf.get('overall_agency', '?')} | "
            f"Language: {cf.get('dominant_language', '?')}"
        )

    # Audio features summary
    if audio_features:
        af = audio_features
        sections.append(
            f"AUDIO SUMMARY: "
            f"speech_rate={af.get('session_speech_rate_wpm', '?')} wpm, "
            f"pitch_mean={af.get('session_pitch_mean_hz', '?')} Hz, "
            f"energy_mean={af.get('session_energy_mean_db', '?')} dB, "
            f"reliability={af.get('reliability_score', 0):.2f}"
        )
        pauses = af.get("pauses", [])
        if pauses:
            significant = [p for p in pauses if p.get("duration_ms", 0) > 1000]
            if significant:
                p_lines = [
                    f"  - {p['duration_ms']}ms pause at turn {p.get('turn_index', '?')}: {p.get('context', '')}"
                    for p in significant[:5]
                ]
                sections.append(f"SIGNIFICANT PAUSES ({len(significant)} total):\n" + "\n".join(p_lines))

        dysfluencies = af.get("dysfluencies", [])
        if dysfluencies:
            d_lines = [
                f"  - Turn {d['turn_index']}: {d.get('dysfluency_type', '?')} — \"{d.get('text', '')}\""
                for d in dysfluencies[:5]
            ]
            sections.append(f"DYSFLUENCIES ({len(dysfluencies)} total):\n" + "\n".join(d_lines))

        # Per-turn confidence volatility from window summaries
        window_sums = af.get("window_summaries", [])
        if window_sums:
            vol_lines = [
                f"  - {ws.get('topic_key', '?')}: confidence_volatility={ws.get('confidence_volatility', '?')}"
                for ws in window_sums if ws.get("confidence_volatility") is not None
            ]
            if vol_lines:
                sections.append("AUDIO CONFIDENCE VOLATILITY:\n" + "\n".join(vol_lines))

    # Video features summary
    if video_features:
        vf = video_features
        sections.append(
            f"VIDEO SUMMARY: "
            f"face_visible={vf.get('total_face_visible_pct', 0):.1f}%, "
            f"reliability={vf.get('reliability_score', 0):.2f}"
        )
        turn_vf = vf.get("turn_features", [])
        if turn_vf:
            notable = [
                t for t in turn_vf
                if t.get("engagement_estimate") in ("disengaged", "highly_engaged")
                or t.get("tension_event_count", 0) > 0
            ]
            if notable:
                v_lines = [
                    f"  - Turn {t['turn_index']}: engagement={t.get('engagement_estimate', '?')}, "
                    f"gaze={t.get('dominant_gaze', '?')}, tension={t.get('tension_event_count', 0)}"
                    for t in notable[:8]
                ]
                sections.append("NOTABLE VIDEO MOMENTS:\n" + "\n".join(v_lines))

    # Topic windows
    if topic_windows:
        tw_lines = [
            f"  - {w.get('topic_key', '?')}: {w.get('start_ms', 0)}-{w.get('end_ms', 0)}ms, "
            f"turns={w.get('source_turn_indices', [])}, reliability={w.get('reliability_score', 0):.2f}"
            for w in topic_windows[:15]
        ]
        sections.append("TOPIC WINDOWS:\n" + "\n".join(tw_lines))

    # Evidence graph (hypotheses, correlations)
    if evidence_graph:
        hypotheses = evidence_graph.get("hypotheses", [])
        if hypotheses:
            h_lines = [
                f"  - {h.get('construct_key', '?')} ({h.get('label', '?')}): "
                f"status={h.get('status', '?')}, score={h.get('score', '?')}, "
                f"evidence: {h.get('evidence_summary', '')}"
                for h in hypotheses[:10]
            ]
            sections.append("HYPOTHESES:\n" + "\n".join(h_lines))

        correlations = evidence_graph.get("correlations", [])
        if correlations:
            c_lines = [
                f"  - {c.get('type', '?')}: {c.get('description', '')}"
                for c in correlations[:10]
            ]
            sections.append("CROSS-MODAL CORRELATIONS:\n" + "\n".join(c_lines))

        edges = evidence_graph.get("edges", [])
        if edges:
            e_lines = [
                f"  - [{e.get('edge_type', '?')}] {e.get('source', '?')} → {e.get('target', '?')}: "
                f"{e.get('label', '')}"
                for e in edges[:10]
            ]
            sections.append(f"EVIDENCE EDGES ({len(edges)} total):\n" + "\n".join(e_lines))

    return "\n\n".join(sections) if sections else "No evidence features available."


# ---------------------------------------------------------------------------
# Public prompt builders
# ---------------------------------------------------------------------------

class PromptBuilder:
    """Constructs prompts for each profile synthesis step."""

    def build_counsellor_prompt(
        self,
        session_id: uuid.UUID,
        turns: list[dict],
        content_features: dict | None = None,
        audio_features: dict | None = None,
        video_features: dict | None = None,
        evidence_graph: dict | None = None,
        topic_windows: list[dict] | None = None,
        student_context: str | None = None,
    ) -> tuple[str, str]:
        """Build system + user prompt for counsellor profile synthesis.

        Returns:
            (system_prompt, user_prompt)
        """
        transcript = _format_transcript_summary(turns)
        evidence = _format_evidence_context(
            content_features, audio_features, video_features,
            evidence_graph, topic_windows,
        )

        user_parts = [
            f"SESSION ID: {session_id}",
            "",
            "=== TRANSCRIPT ===",
            transcript,
            "",
            "=== EVIDENCE ===",
            evidence,
        ]

        if student_context:
            user_parts.extend([
                "",
                "=== PRIOR SESSION CONTEXT ===",
                student_context,
            ])

        user_parts.extend([
            "",
            "=== TASK ===",
            "Synthesize a counsellor profile from the above evidence. "
            "Return valid JSON matching the counsellor view schema.",
        ])

        return _COUNSELLOR_SYSTEM, "\n".join(user_parts)

    def build_student_prompt(
        self,
        session_id: uuid.UUID,
        counsellor_profile: dict,
        turns: list[dict],
    ) -> tuple[str, str]:
        """Build system + user prompt for student-facing profile.

        Uses the counsellor profile as input to derive a simpler,
        encouraging student view.

        Returns:
            (system_prompt, user_prompt)
        """
        # Give the LLM the constructs and summary (not red flags)
        safe_input = {
            "summary": counsellor_profile.get("summary", ""),
            "constructs": [
                {
                    "label": c.get("label", ""),
                    "status": c.get("status", ""),
                    "evidence_summary": c.get("evidence_summary", ""),
                }
                for c in counsellor_profile.get("constructs", [])
            ],
        }

        # Include a few student quotes for personalization
        quotes: list[str] = []
        for c in counsellor_profile.get("constructs", []):
            quotes.extend(c.get("supporting_quotes", [])[:2])

        user_parts = [
            f"SESSION ID: {session_id}",
            "",
            "=== COUNSELLOR ANALYSIS (use as basis, do NOT expose directly) ===",
            json.dumps(safe_input, indent=2),
            "",
            "=== STUDENT QUOTES (for personalization) ===",
            "\n".join(f'- "{q}"' for q in quotes[:6]) if quotes else "No quotes available.",
            "",
            "=== TASK ===",
            "Create a warm, encouraging student-facing profile. "
            "Return valid JSON matching the student view schema.",
        ]

        return _STUDENT_SYSTEM, "\n".join(user_parts)

    def build_school_prompt(
        self,
        session_id: uuid.UUID,
        counsellor_profile: dict,
    ) -> tuple[str, str]:
        """Build system + user prompt for school-level profile summary.

        Returns:
            (system_prompt, user_prompt)
        """
        # Aggregate-safe input: topics, risk level, engagement
        topics = [c.get("label", "") for c in counsellor_profile.get("constructs", [])]
        red_flags = counsellor_profile.get("red_flags", [])

        max_severity = "low"
        for rf in red_flags:
            sev = rf.get("severity", "low")
            if sev == "high":
                max_severity = "high"
                break
            elif sev == "medium":
                max_severity = "medium"

        user_parts = [
            f"SESSION ID: {session_id}",
            "",
            "=== SESSION SUMMARY ===",
            counsellor_profile.get("summary", "No summary available."),
            "",
            f"=== TOPICS DISCUSSED ({len(topics)}) ===",
            "\n".join(f"- {t}" for t in topics) if topics else "None identified.",
            "",
            f"=== RISK INDICATORS ({len(red_flags)} flags, max severity: {max_severity}) ===",
            "\n".join(
                f"- [{rf.get('severity', '?')}] {rf.get('key', '?')}"
                for rf in red_flags
            ) if red_flags else "No red flags.",
            "",
            "=== TASK ===",
            "Create an aggregate-safe school summary. "
            "Return valid JSON matching the school view schema.",
        ]

        return _SCHOOL_SYSTEM, "\n".join(user_parts)

    @staticmethod
    def get_json_schema(view: str) -> dict[str, Any]:
        """Get the JSON schema for a specific profile view.

        Args:
            view: One of 'counsellor', 'student', 'school'.
        """
        schemas = {
            "counsellor": COUNSELLOR_VIEW_SCHEMA,
            "student": STUDENT_VIEW_SCHEMA,
            "school": SCHOOL_VIEW_SCHEMA,
        }
        return schemas.get(view, {})
