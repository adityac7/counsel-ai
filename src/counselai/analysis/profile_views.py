"""Adapters between raw profile output and dashboard-facing profile views."""

from __future__ import annotations

from typing import Any


def _normalize_score(value: Any) -> float | None:
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if numeric > 1:
        numeric = numeric / 10.0
    return max(0.0, min(1.0, numeric))


def _score_status(score: float | None) -> str:
    if score is None:
        return "mixed"
    if score >= 0.7:
        return "supported"
    if score >= 0.4:
        return "mixed"
    return "weak"


def _normalize_red_flags(raw_flags: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_flags, list):
        return []

    normalized: list[dict[str, Any]] = []
    for idx, item in enumerate(raw_flags):
        if isinstance(item, dict):
            normalized.append(
                {
                    "key": item.get("key") or item.get("label") or f"red_flag_{idx + 1}",
                    "severity": item.get("severity") or "medium",
                    "reason": item.get("reason") or item.get("summary") or "",
                    "recommended_action": item.get("recommended_action"),
                    "evidence_refs": item.get("evidence_refs") or [],
                }
            )
            continue

        text = str(item).strip()
        if not text:
            continue
        normalized.append(
            {
                "key": text,
                "severity": "medium",
                "reason": text,
                "recommended_action": "Review this concern in the next counselling follow-up.",
                "evidence_refs": [],
            }
        )
    return normalized


def _string_list(raw_values: Any) -> list[str]:
    if isinstance(raw_values, str):
        raw_values = [raw_values]
    if not isinstance(raw_values, list):
        return []

    values: list[str] = []
    seen: set[str] = set()
    for item in raw_values:
        text = str(item or "").strip()
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        values.append(text)
    return values


def _default_student_view() -> dict[str, Any]:
    return {
        "strengths": [],
        "interests": [],
        "growth_areas": [],
        "suggested_next_steps": [],
        "summary": "",
        "encouragement": "",
    }


def _build_growth_areas(profile: dict[str, Any]) -> list[str]:
    cognitive = profile.get("cognitive_profile") or {}
    emotional = profile.get("emotional_profile") or {}
    behavioral = profile.get("behavioral_insights") or {}

    growth_areas: list[str] = []
    if (_normalize_score(cognitive.get("critical_thinking")) or 1) < 0.7:
        growth_areas.append("Thinking through consequences")
    if (_normalize_score(cognitive.get("perspective_taking")) or 1) < 0.7:
        growth_areas.append("Considering other viewpoints")
    if (_normalize_score(emotional.get("eq_score")) or 1) < 0.7:
        growth_areas.append("Naming emotions clearly")
    if (_normalize_score(behavioral.get("confidence")) or 1) < 0.7:
        growth_areas.append("Confidence in difficult situations")
    return growth_areas[:4]


def build_student_profile_view(profile: dict[str, Any] | None) -> dict[str, Any]:
    """Create the student-safe profile view consumed by the student dashboard."""
    if not isinstance(profile, dict) or not profile:
        return _default_student_view()

    traits = _string_list((profile.get("personality_snapshot") or {}).get("traits"))
    recommendations = _string_list(profile.get("recommendations"))
    summary = str(profile.get("summary") or "").strip()
    growth_areas = _build_growth_areas(profile)

    encouragement = ""
    if traits:
        lead = ", ".join(traits[:2])
        encouragement = f"You already show {lead}. Keep building on that."
    elif summary:
        encouragement = "You are already reflecting on your choices. Keep building on that."

    return {
        "strengths": traits[:6],
        "interests": [],
        "growth_areas": growth_areas,
        "suggested_next_steps": recommendations[:4],
        "summary": summary,
        "encouragement": encouragement,
    }


def build_school_profile_view(
    profile: dict[str, Any] | None,
    *,
    normalized_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a school-safe aggregate view for dashboard topic fallbacks."""
    if not isinstance(profile, dict) or not profile:
        return {"summary": "", "themes": []}

    normalized = normalized_profile or normalize_profile_for_dashboard(profile) or {}
    red_flags = normalized.get("red_flags") if isinstance(normalized, dict) else []
    counsellor_view = (
        normalized.get("counsellor_view") if isinstance(normalized, dict) else {}
    ) or {}
    constructs = counsellor_view.get("constructs") if isinstance(counsellor_view, dict) else []

    themes = _string_list(
        [flag.get("key") for flag in red_flags if isinstance(flag, dict)]
        + [
            construct.get("key")
            for construct in constructs
            if isinstance(construct, dict) and construct.get("status") != "weak"
        ]
    )
    return {
        "summary": str(profile.get("summary") or "").strip(),
        "themes": themes[:8],
    }


def build_construct_hypotheses(
    normalized_profile: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Convert counsellor constructs into hypothesis rows."""
    if not isinstance(normalized_profile, dict):
        return []

    counsellor_view = normalized_profile.get("counsellor_view") or {}
    constructs = counsellor_view.get("constructs") if isinstance(counsellor_view, dict) else []
    hypotheses: list[dict[str, Any]] = []

    for construct in constructs:
        if not isinstance(construct, dict):
            continue

        construct_key = str(construct.get("key") or "").strip()
        label = str(construct.get("label") or "").strip()
        if not construct_key or not label:
            continue

        score = _normalize_score(construct.get("score"))
        status = str(construct.get("status") or _score_status(score)).strip()
        evidence_summary = str(construct.get("evidence_summary") or "").strip()
        evidence_refs = construct.get("evidence_refs") or []

        hypotheses.append(
            {
                "construct_key": construct_key,
                "label": label,
                "status": status,
                "score": score,
                "evidence_summary": evidence_summary or "No evidence summary captured.",
                "evidence_refs": {"refs": evidence_refs},
            }
        )

    return hypotheses


def build_dashboard_profile_payload(
    profile: dict[str, Any] | None,
    *,
    normalized_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the durable dashboard payloads derived from a raw profile."""
    normalized = normalized_profile or normalize_profile_for_dashboard(profile) or {}
    return {
        "student_view": build_student_profile_view(profile),
        "counsellor_view": normalized.get("counsellor_view", {}) if isinstance(normalized, dict) else {},
        "school_view": build_school_profile_view(profile, normalized_profile=normalized),
        "red_flags": normalized.get("red_flags", []) if isinstance(normalized, dict) else [],
        "hypotheses": build_construct_hypotheses(normalized),
    }


def normalize_profile_for_dashboard(profile: dict[str, Any] | None) -> dict[str, Any] | None:
    """Return a profile payload shaped for counsellor dashboard rendering."""
    if not isinstance(profile, dict) or not profile:
        return None

    if "counsellor_view" in profile:
        normalized = dict(profile)
        normalized["red_flags"] = _normalize_red_flags(profile.get("red_flags"))
        return normalized

    cognitive = profile.get("cognitive_profile") or {}
    emotional = profile.get("emotional_profile") or {}
    behavioral = profile.get("behavioral_insights") or {}
    reasoning = profile.get("reasoning") or {}
    key_moments = profile.get("key_moments") or []
    quotes = [
        moment.get("quote")
        for moment in key_moments
        if isinstance(moment, dict) and moment.get("quote")
    ][:2]

    construct_specs = [
        (
            "critical_thinking",
            "Critical Thinking",
            cognitive.get("critical_thinking"),
            reasoning.get("critical_thinking"),
        ),
        (
            "perspective_taking",
            "Perspective Taking",
            cognitive.get("perspective_taking"),
            reasoning.get("perspective_taking"),
        ),
        (
            "eq_score",
            "Emotional Intelligence",
            emotional.get("eq_score"),
            reasoning.get("eq_score"),
        ),
        (
            "confidence",
            "Confidence",
            behavioral.get("confidence"),
            reasoning.get("confidence"),
        ),
    ]

    constructs = []
    for key, label, raw_score, summary in construct_specs:
        score = _normalize_score(raw_score)
        if score is None and not summary:
            continue
        constructs.append(
            {
                "key": key,
                "label": label,
                "score": score,
                "status": _score_status(score),
                "evidence_summary": summary or "",
                "supporting_quotes": quotes,
                "evidence_refs": [],
            }
        )

    return {
        "counsellor_view": {
            "summary": profile.get("summary") or "",
            "constructs": constructs,
            "cross_modal_notes": [],
            "recommended_follow_ups": profile.get("recommendations") or [],
        },
        "red_flags": _normalize_red_flags(profile.get("red_flags")),
    }
