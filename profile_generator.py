"""Generate student profiles from counselling sessions."""

from __future__ import annotations

from typing import Any, Dict, List
import json
import os

from openai import OpenAI


PROFILE_PROMPT = (
    "You are an expert school counsellor summarizer. Using the full session data, "
    "produce a structured student profile. Be balanced, evidence-based, and avoid diagnosis. "
    "Quote the student when relevant. Return strict JSON only.\n\n"
    "Required JSON schema: {"
    "summary: string, "
    "personality_snapshot: {traits: [...], communication_style: string, decision_making: string}, "
    "cognitive_profile: {critical_thinking: int, perspective_taking: int, moral_reasoning_stage: string, "
    "problem_solving_style: string}, "
    "emotional_profile: {eq_score: int, empathy_level: string, stress_response: string, "
    "anxiety_markers: [string], emotional_vocabulary: string}, "
    "behavioral_insights: {confidence: int, leadership_potential: string, peer_influence: string, "
    "academic_pressure: string, resilience: string}, "
    "conversation_analysis: {evolution_across_rounds: string, consistency: string}, "
    "key_moments: [{quote: string, insight: string}], "
    "reasoning: {critical_thinking: string, perspective_taking: string, eq_score: string, confidence: string}, "
    "red_flags: [string], "
    "recommendations: [string]"
    "}"
)


def _safe_json_loads(raw: str) -> Dict[str, Any]:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # Best-effort extraction if model returns extra text
        start = raw.find("{")
        end = raw.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(raw[start : end + 1])
            except json.JSONDecodeError:
                return {}
        return {}


def generate_profile(session_data: Dict[str, Any]) -> Dict[str, Any]:
    """Generate a comprehensive profile from session data using GPT-5.2."""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise EnvironmentError("OPENAI_API_KEY is not set")

    client = OpenAI(api_key=api_key, timeout=60)
    user_prompt = f"Session data: {session_data}"

    try:
        response = client.chat.completions.create(
            model="gpt-5.2",
            messages=[
                {"role": "system", "content": PROFILE_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.4,
            max_completion_tokens=2500,
        )
        raw = response.choices[0].message.content.strip()
        profile = _safe_json_loads(raw)
        return profile
    except Exception as exc:  # noqa: BLE001
        return {
            "error": f"GPT-5.2 call failed: {type(exc).__name__}: {exc}",
            "summary": "",
            "personality_snapshot": {},
            "cognitive_profile": {},
            "emotional_profile": {},
            "behavioral_insights": {},
            "conversation_analysis": {},
            "key_moments": [],
            "reasoning": {},
            "red_flags": [],
            "recommendations": [],
        }


def _compare_profiles(primary: Dict[str, Any], secondary: Dict[str, Any]) -> Dict[str, Any]:
    diffs: List[Dict[str, Any]] = []
    list_diffs: List[Dict[str, Any]] = []

    def compare_scalar(path: str, a: Any, b: Any) -> None:
        if a is None or b is None:
            return
        if isinstance(a, (int, float, str)) and isinstance(b, (int, float, str)) and a != b:
            diffs.append({"path": path, "primary": a, "secondary": b, "match": False})
        elif isinstance(a, (int, float, str)) and isinstance(b, (int, float, str)):
            diffs.append({"path": path, "primary": a, "secondary": b, "match": True})

    def compare_list(path: str, a: Any, b: Any) -> None:
        if isinstance(a, list) and isinstance(b, list) and len(a) != len(b):
            list_diffs.append(
                {"path": path, "primary_len": len(a), "secondary_len": len(b), "match": False}
            )

    compare_scalar(
        "cognitive_profile.critical_thinking",
        primary.get("cognitive_profile", {}).get("critical_thinking"),
        secondary.get("cognitive_profile", {}).get("critical_thinking"),
    )
    compare_scalar(
        "cognitive_profile.perspective_taking",
        primary.get("cognitive_profile", {}).get("perspective_taking"),
        secondary.get("cognitive_profile", {}).get("perspective_taking"),
    )
    compare_scalar(
        "emotional_profile.eq_score",
        primary.get("emotional_profile", {}).get("eq_score"),
        secondary.get("emotional_profile", {}).get("eq_score"),
    )
    compare_scalar(
        "behavioral_insights.confidence",
        primary.get("behavioral_insights", {}).get("confidence"),
        secondary.get("behavioral_insights", {}).get("confidence"),
    )
    compare_list("key_moments", primary.get("key_moments"), secondary.get("key_moments"))
    compare_list("red_flags", primary.get("red_flags"), secondary.get("red_flags"))

    return {
        "scalar_diffs": diffs,
        "list_diffs": list_diffs,
        "summary": {
            "scalar_mismatches": sum(1 for d in diffs if not d["match"]),
            "list_mismatches": sum(1 for d in list_diffs if not d["match"]),
        },
    }


def cross_validate(session_data: Dict[str, Any], primary_profile: Dict[str, Any]) -> Dict[str, Any]:
    """Cross-validate with MiniMax M2.5 and flag discrepancies."""
    api_key = os.getenv("MINIMAX_API_KEY")
    if not api_key:
        raise EnvironmentError("MINIMAX_API_KEY is not set")

    client = OpenAI(api_key=api_key, base_url="https://api.minimax.io/v1")
    user_prompt = (
        "Generate the same profile JSON for this session data, using the provided schema. "
        "Return strict JSON only.\n\n"
        f"Session data: {session_data}"
    )

    try:
        response = client.chat.completions.create(
            model="MiniMax-M2.5",
            messages=[
                {"role": "system", "content": PROFILE_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.4,
            max_completion_tokens=1200,
        )
        raw = response.choices[0].message.content.strip()
        secondary_profile = _safe_json_loads(raw)
        discrepancies = _compare_profiles(primary_profile, secondary_profile)
        return {
            "secondary_profile": secondary_profile,
            "comparison": discrepancies,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "error": f"MiniMax call failed: {type(exc).__name__}: {exc}",
            "secondary_profile": {},
            "comparison": {"scalar_diffs": [], "list_diffs": [], "summary": {}},
        }
