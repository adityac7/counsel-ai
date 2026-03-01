import json
from types import SimpleNamespace

import profile_generator


def _fake_openai_factory(payload):
    class _FakeCompletions:
        def create(self, *args, **kwargs):
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))
                ]
            )

    class _FakeChat:
        def __init__(self):
            self.completions = _FakeCompletions()

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            self.chat = _FakeChat()

    return _FakeClient


def test_generate_profile_new_fields(monkeypatch):
    mock_profile = {
        "summary": "The student shows a considerate moral stance and prefers private resolution. "
        "They balance empathy with a clear stance against cheating. "
        "Responses are concise and grounded in fairness. "
        "Overall, the profile suggests steady judgment with modest emotional awareness.",
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
            "emotional_vocabulary": "basic",
        },
        "behavioral_insights": {
            "confidence": 6,
            "leadership_potential": "emerging",
            "peer_influence": "positive",
            "academic_pressure": "low",
            "resilience": "steady",
        },
        "conversation_analysis": {
            "evolution_across_rounds": "consistent with initial stance",
            "consistency": "high",
        },
        "key_moments": [
            {
                "quote": "I would talk to him privately first",
                "insight": "Shows preference for discretion and relationship preservation.",
            },
            {
                "quote": "I dont want to embarrass him but cheating is wrong",
                "insight": "Balances empathy with a clear moral boundary.",
            },
        ],
        "reasoning": {
            "critical_thinking": "Provides a reasoned, stepwise approach to conflict.",
            "perspective_taking": "Considers the friend's feelings and public impact.",
            "eq_score": "Recognizes emotional consequences while holding standards.",
            "confidence": "Speaks with clarity but without assertive dominance.",
        },
        "red_flags": [],
        "recommendations": ["Encourage elaboration on alternatives and consequences."],
    }

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(profile_generator, "OpenAI", _fake_openai_factory(mock_profile))

    transcript = [
        {"role": "counsellor", "content": "What would you do if your friend was cheating?"},
        {"role": "student", "content": "I would talk to him privately first"},
        {"role": "counsellor", "content": "What makes you say that?"},
        {"role": "student", "content": "I dont want to embarrass him but cheating is wrong"},
    ]
    session_data = {"transcript": transcript}

    profile = profile_generator.generate_profile(session_data)

    assert "summary" in profile
    assert "key_moments" in profile
    assert "reasoning" in profile
    assert "personality_snapshot" in profile
    assert "cognitive_profile" in profile
    assert "emotional_profile" in profile
    assert "behavioral_insights" in profile
    assert "conversation_analysis" in profile
    assert "recommendations" in profile
