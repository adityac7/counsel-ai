"""Tests for the unified session analyzer.

Mocks the Gemini client's generate_content method and verifies the result
matches the expected ANALYSIS_SCHEMA keys.
"""

import json
from unittest.mock import MagicMock, patch

from counselai.analysis.unified_analyzer import analyze_session, ANALYSIS_SCHEMA


def _fake_analysis_result():
    """Return a mock analysis result matching ANALYSIS_SCHEMA."""
    return {
        "session_summary": "The student shows a considerate moral stance and prefers private resolution.",
        "engagement_score": 7,
        "key_themes": [
            {"theme": "peer_pressure", "evidence": "Friend was cheating", "severity": "medium"},
        ],
        "emotional_analysis": {
            "primary_emotion": "concern",
            "secondary_emotions": ["empathy"],
            "trajectory": "steady",
            "emotional_vocabulary": "developing",
        },
        "risk_assessment": {
            "level": "low",
            "flags": [],
            "protective_factors": ["strong moral compass"],
            "immediate_safety_concern": False,
        },
        "constructs": [
            {
                "key": "critical_thinking",
                "label": "Critical Thinking",
                "score": 0.7,
                "status": "supported",
                "evidence_summary": "Provides a reasoned, stepwise approach to conflict.",
            },
        ],
        "personality_snapshot": {
            "traits": ["considerate", "principled"],
            "communication_style": "concise and thoughtful",
            "decision_making": "prioritizes discretion and fairness",
        },
        "cognitive_profile": {
            "critical_thinking": 7,
            "perspective_taking": 7,
            "moral_reasoning_stage": "conventional",
            "problem_solving_style": "collaborative",
        },
        "emotional_profile": {
            "eq_score": 6,
            "empathy_level": "moderate",
            "stress_response": "calm",
            "anxiety_markers": [],
        },
        "behavioral_insights": {
            "confidence": 6,
            "leadership_potential": "emerging",
            "peer_influence": "positive",
            "academic_pressure": "low",
            "resilience": "steady",
        },
        "key_moments": [
            {
                "quote": "I would talk to him privately first",
                "insight": "Shows preference for discretion and relationship preservation.",
            },
        ],
        "student_view": {
            "strengths": ["Moral clarity", "Empathy"],
            "interests": [],
            "growth_areas": ["Assertiveness"],
            "encouragement": "Your thoughtfulness shows real maturity.",
            "next_steps": ["Encourage elaboration on alternatives."],
        },
        "school_view": {
            "themes": ["peer_dynamics"],
            "academic_pressure_level": "none",
        },
        "follow_up": {
            "actions": ["Discuss peer dynamics further"],
            "referral_needed": False,
            "urgency": "routine",
        },
        "red_flags": [],
        "recommendations": ["Encourage elaboration on alternatives and consequences."],
        "face_data": {
            "dominant_emotion": "concern",
            "engagement_indicators": "Maintains steady focus throughout the scenario.",
        },
        "voice_data": {
            "speech_patterns": "Measured and deliberate",
            "confidence_level": "Moderate",
        },
        "segment_analysis": [
            {
                "segment_name": "Opening response",
                "content_summary": "Student prefers private intervention before escalation.",
                "emotional_state": "calm",
            },
        ],
    }


def test_analyze_session_returns_expected_schema_keys(monkeypatch):
    """analyze_session should return all top-level keys from ANALYSIS_SCHEMA."""
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    mock_result = _fake_analysis_result()
    mock_response = MagicMock()
    mock_response.text = json.dumps(mock_result)

    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = mock_response

    with patch("counselai.analysis.unified_analyzer.genai") as mock_genai:
        mock_genai.Client.return_value = mock_client

        transcript = [
            {"role": "counsellor", "text": "What would you do if your friend was cheating?"},
            {"role": "student", "text": "I would talk to him privately first"},
            {"role": "counsellor", "text": "What makes you say that?"},
            {"role": "student", "text": "I dont want to embarrass him but cheating is wrong"},
        ]

        result = analyze_session(
            transcript,
            student_name="Test Student",
            student_grade="10",
            case_study="ethics-01",
            duration_seconds=300,
        )

    # Verify all required top-level keys from the schema are present
    required_keys = ANALYSIS_SCHEMA["required"]
    for key in required_keys:
        assert key in result, f"Missing required key: {key}"

    # Verify specific nested structures
    assert "session_summary" in result
    assert "risk_assessment" in result
    assert "constructs" in result
    assert "student_view" in result
    assert "school_view" in result
    assert "key_moments" in result
    assert "personality_snapshot" in result
    assert "cognitive_profile" in result
    assert "emotional_profile" in result
    assert "behavioral_insights" in result
    assert "recommendations" in result
    assert "red_flags" in result

    # Verify nested schema shapes
    assert "level" in result["risk_assessment"]
    assert "flags" in result["risk_assessment"]
    assert isinstance(result["constructs"], list)
    assert isinstance(result["key_moments"], list)


def test_analyze_session_calls_gemini_with_transcript(monkeypatch):
    """Verify that analyze_session passes transcript content to Gemini."""
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    mock_result = _fake_analysis_result()
    mock_response = MagicMock()
    mock_response.text = json.dumps(mock_result)

    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = mock_response

    with patch("counselai.analysis.unified_analyzer.genai") as mock_genai:
        mock_genai.Client.return_value = mock_client

        transcript = [
            {"role": "student", "text": "I feel pressured by my friends."},
        ]

        analyze_session(transcript, student_name="Arjun", student_grade="11")

    # Verify Gemini was called exactly once
    mock_client.models.generate_content.assert_called_once()

    # Verify the prompt includes transcript content
    call_args = mock_client.models.generate_content.call_args
    contents = call_args.kwargs.get("contents") or call_args[1].get("contents")
    prompt_text = contents[0] if isinstance(contents, list) else str(contents)
    assert "I feel pressured" in prompt_text
