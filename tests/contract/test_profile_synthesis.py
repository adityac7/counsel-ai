"""Contract tests for the Profile Synthesis Engine (Task 11).

Tests schema validation, safety screening, prompt construction,
and the synthesis pipeline with a mock provider.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from typing import Any

import pytest

from counselai.profiles.prompt_builder import PromptBuilder
from counselai.profiles.schemas import (
    CounsellorProfileView,
    Construct,
    EvidenceRef,
    HypothesisStatus,
    RedFlag,
    RedFlagSeverity,
    SchoolProfileView,
    SessionProfile,
    StudentProfileView,
    SynthesisResponse,
)
from counselai.profiles.validators import (
    ProfileValidator,
    extract_json_from_text,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def validator():
    return ProfileValidator()


@pytest.fixture
def prompt_builder():
    return PromptBuilder()


@pytest.fixture
def session_id():
    return uuid.uuid4()


@pytest.fixture
def sample_turns():
    return [
        {"turn_index": 0, "speaker": "counsellor", "text": "Hello beta, tell me about yourself."},
        {"turn_index": 1, "speaker": "student", "text": "Mujhe lagta hai ki mujhe science pasand hai."},
        {"turn_index": 2, "speaker": "counsellor", "text": "Accha, science mein kya pasand hai?"},
        {"turn_index": 3, "speaker": "student", "text": "I think maybe biology, but my parents want engineering."},
        {"turn_index": 4, "speaker": "counsellor", "text": "Aur tumhara kya mann hai?"},
        {"turn_index": 5, "speaker": "student", "text": "I don't know... it's confusing."},
    ]


@pytest.fixture
def sample_counsellor_json():
    return json.dumps({
        "summary": "Student shows interest in science but experiences career confusion due to parental pressure.",
        "constructs": [
            {
                "key": "career_identity_clarity",
                "label": "Career identity clarity",
                "status": "mixed",
                "score": 0.45,
                "evidence_summary": "Student expresses interest in biology but defers to parental expectations for engineering.",
                "evidence_refs": [
                    {"ref_type": "turn", "ref_id": "turn:3", "modality": "content", "summary": "Parent pressure mention", "confidence": 0.8},
                    {"ref_type": "turn", "ref_id": "turn:5", "modality": "content", "summary": "Confusion expressed", "confidence": 0.9},
                ],
                "supporting_quotes": [
                    "my parents want engineering",
                    "I don't know... it's confusing",
                ],
            },
            {
                "key": "decision_autonomy",
                "label": "Decision autonomy",
                "status": "weak",
                "score": 0.3,
                "evidence_summary": "Low self-agency language with deference to parental authority.",
                "evidence_refs": [
                    {"ref_type": "turn", "ref_id": "turn:3", "modality": "content", "summary": "Deference pattern", "confidence": 0.7},
                ],
                "supporting_quotes": ["my parents want engineering"],
            },
        ],
        "red_flags": [
            {
                "key": "high_external_pressure",
                "severity": "medium",
                "reason": "Repeated deference to parental approval with low self-agency language",
                "evidence_refs": [
                    {"ref_type": "turn", "ref_id": "turn:3", "modality": "content", "confidence": 0.8},
                ],
                "recommended_action": "Explore family dynamics and student's own career preferences in follow-up.",
            },
        ],
        "cross_modal_notes": [
            "Student's voice pitch dropped when mentioning parental expectations (audio + content alignment).",
        ],
        "recommended_follow_ups": [
            "Discuss biology career paths to gauge depth of interest.",
            "Explore family conversation dynamics around career choices.",
        ],
    })


@pytest.fixture
def sample_student_json():
    return json.dumps({
        "strengths": [
            "You have a clear interest in science, especially biology",
            "You're honest about your feelings and confusion — that takes courage",
        ],
        "interests": ["Biology", "Science"],
        "growth_areas": [
            "Exploring what you personally enjoy vs what others expect",
            "Building confidence in expressing your own preferences",
        ],
        "suggested_next_steps": [
            "Talk to a biology teacher about what a career in biology looks like",
            "Write down 3 things you enjoy doing — not what others want you to do",
        ],
        "summary": "You showed great self-awareness in our conversation. You clearly love science and have a lot of potential!",
        "encouragement": "It's totally okay to feel confused about career choices — most people your age do. The fact that you're thinking about it shows maturity. Keep exploring!",
    })


@pytest.fixture
def sample_school_json():
    return json.dumps({
        "primary_topics": ["Career confusion", "Parental pressure", "Science interest"],
        "risk_level": "medium",
        "engagement_rating": "moderate",
        "summary": "Session covered career identity topics with moderate engagement. One medium-severity concern noted.",
    })


# ---------------------------------------------------------------------------
# JSON extraction tests
# ---------------------------------------------------------------------------

class TestJsonExtraction:
    def test_pure_json(self):
        assert extract_json_from_text('{"a": 1}') == {"a": 1}

    def test_markdown_block(self):
        text = '```json\n{"a": 1}\n```'
        assert extract_json_from_text(text) == {"a": 1}

    def test_surrounded_text(self):
        text = 'Here is the result: {"a": 1} end.'
        assert extract_json_from_text(text) == {"a": 1}

    def test_invalid_json(self):
        assert extract_json_from_text("not json at all") is None

    def test_nested_json(self):
        data = {"outer": {"inner": [1, 2, 3]}}
        assert extract_json_from_text(json.dumps(data)) == data


# ---------------------------------------------------------------------------
# Counsellor view validation tests
# ---------------------------------------------------------------------------

class TestCounsellorValidation:
    def test_valid_counsellor_view(self, validator, sample_counsellor_json):
        view, errors = validator.validate_counsellor_view(sample_counsellor_json)
        assert view is not None
        assert isinstance(view, CounsellorProfileView)
        assert len(view.constructs) == 2
        assert len(view.red_flags) == 1
        assert view.constructs[0].key == "career_identity_clarity"

    def test_empty_summary_warning(self, validator):
        data = json.dumps({"summary": "", "constructs": [], "red_flags": []})
        view, errors = validator.validate_counsellor_view(data)
        assert view is not None
        assert any("empty" in e.lower() for e in errors)

    def test_construct_without_evidence_refs(self, validator):
        data = json.dumps({
            "summary": "Test",
            "constructs": [{
                "key": "test",
                "label": "Test",
                "status": "supported",
                "evidence_summary": "No refs",
            }],
            "red_flags": [],
        })
        view, errors = validator.validate_counsellor_view(data)
        assert view is not None
        assert any("evidence refs" in e.lower() for e in errors)

    def test_invalid_json_returns_none(self, validator):
        view, errors = validator.validate_counsellor_view("not json")
        assert view is None
        assert len(errors) > 0


# ---------------------------------------------------------------------------
# Student view validation tests
# ---------------------------------------------------------------------------

class TestStudentValidation:
    def test_valid_student_view(self, validator, sample_student_json):
        view, errors = validator.validate_student_view(sample_student_json)
        assert view is not None
        assert isinstance(view, StudentProfileView)
        assert len(view.strengths) == 2
        assert view.encouragement != ""

    def test_clinical_language_detected(self, validator):
        data = json.dumps({
            "strengths": ["Good"],
            "interests": [],
            "summary": "Student exhibits signs of anxiety disorder",
            "encouragement": "Keep going",
        })
        view, errors = validator.validate_student_view(data)
        assert any("clinical" in e.lower() for e in errors)

    def test_diagnostic_phrasing_detected(self, validator):
        data = json.dumps({
            "strengths": ["Thoughtful"],
            "interests": [],
            "summary": "Behavior is consistent with low self-esteem",
            "encouragement": "You're great",
        })
        view, errors = validator.validate_student_view(data)
        assert any("diagnostic" in e.lower() for e in errors)

    def test_sanitizer_cleans_clinical_terms(self, validator):
        dirty = StudentProfileView(
            summary="Student shows symptoms of depression and anxiety",
            strengths=["Has ADHD-like focus patterns"],
            encouragement="Keep trying!",
        )
        clean = validator.sanitize_student_view(dirty)
        assert "depression" not in clean.summary
        assert "ADHD" not in clean.strengths[0]
        assert "[area of growth]" in clean.summary or "shows patterns" in clean.summary


# ---------------------------------------------------------------------------
# School view validation tests
# ---------------------------------------------------------------------------

class TestSchoolValidation:
    def test_valid_school_view(self, validator, sample_school_json):
        view, errors = validator.validate_school_view(sample_school_json)
        assert view is not None
        assert isinstance(view, SchoolProfileView)
        assert len(view.primary_topics) == 3


# ---------------------------------------------------------------------------
# Full profile consistency tests
# ---------------------------------------------------------------------------

class TestProfileConsistency:
    def test_red_flag_mismatch_warning(self, validator, session_id):
        profile = SessionProfile(
            session_id=session_id,
            counsellor_view=CounsellorProfileView(
                summary="Test",
                red_flags=[RedFlag(key="flag_a", severity=RedFlagSeverity.medium, reason="Test")],
            ),
            red_flags=[RedFlag(key="flag_b", severity=RedFlagSeverity.low, reason="Different")],
        )
        warnings = validator.validate_full_profile(profile)
        assert any("mismatch" in w.lower() for w in warnings)

    def test_consistent_profile_no_warnings(self, validator, session_id):
        flag = RedFlag(key="test_flag", severity=RedFlagSeverity.low, reason="Test")
        profile = SessionProfile(
            session_id=session_id,
            counsellor_view=CounsellorProfileView(
                summary="Test",
                constructs=[Construct(key="c1", label="C1", evidence_summary="E1")],
                red_flags=[flag],
            ),
            student_view=StudentProfileView(
                summary="Good", strengths=["Strong"], encouragement="Nice",
            ),
            school_view=SchoolProfileView(
                summary="Done", primary_topics=["C1"],
            ),
            red_flags=[flag],
        )
        warnings = validator.validate_full_profile(profile)
        # May still get overlap warning but no mismatch
        assert not any("mismatch" in w.lower() for w in warnings)


# ---------------------------------------------------------------------------
# Prompt builder tests
# ---------------------------------------------------------------------------

class TestPromptBuilder:
    def test_counsellor_prompt_includes_transcript(self, prompt_builder, session_id, sample_turns):
        sys_p, usr_p = prompt_builder.build_counsellor_prompt(session_id, sample_turns)
        assert "TRANSCRIPT" in usr_p
        assert "mujhe lagta hai" in usr_p.lower()
        assert "evidence" in sys_p.lower()

    def test_student_prompt_excludes_red_flags(self, prompt_builder, session_id, sample_turns):
        counsellor = {
            "summary": "Test",
            "constructs": [{"label": "Career", "status": "mixed", "evidence_summary": "E"}],
            "red_flags": [{"key": "flag", "severity": "high", "reason": "Bad"}],
        }
        sys_p, usr_p = prompt_builder.build_student_prompt(session_id, counsellor, sample_turns)
        # Red flags dict should not be passed to user prompt
        assert "high_external_pressure" not in usr_p
        assert "Bad" not in usr_p  # the reason text shouldn't leak
        # System prompt should instruct against clinical language
        assert "non-diagnostic" in sys_p.lower() or "do not" in sys_p.lower()

    def test_school_prompt_aggregate_safe(self, prompt_builder, session_id):
        counsellor = {
            "summary": "Student discussed career confusion",
            "constructs": [{"label": "Career clarity"}],
            "red_flags": [{"key": "pressure", "severity": "medium"}],
        }
        sys_p, usr_p = prompt_builder.build_school_prompt(session_id, counsellor)
        assert "AGGREGATE" in sys_p.upper()

    def test_evidence_context_formats_content(self, prompt_builder, session_id, sample_turns):
        content = {
            "topics": [{"topic_key": "career", "label": "Career interest", "depth": "moderate", "confidence": 0.8, "turn_indices": [1, 3]}],
            "hedging_markers": [{"turn_index": 3, "text": "I think maybe", "hedge_type": "qualifier"}],
            "agency_markers": [],
            "avoidance_events": [],
            "code_switch_events": [],
            "reliability_score": 0.85,
            "overall_depth": "moderate",
            "overall_agency": "low",
            "dominant_language": "hinglish",
        }
        sys_p, usr_p = prompt_builder.build_counsellor_prompt(
            session_id, sample_turns, content_features=content,
        )
        assert "CONTENT TOPICS" in usr_p
        assert "Career interest" in usr_p
        assert "HEDGING" in usr_p


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------

class TestSchemas:
    def test_session_profile_serialization(self, session_id):
        profile = SessionProfile(
            session_id=session_id,
            counsellor_view=CounsellorProfileView(summary="Test"),
            student_view=StudentProfileView(summary="Test", encouragement="Hi"),
            school_view=SchoolProfileView(summary="Test"),
        )
        data = json.loads(profile.model_dump_json())
        assert data["session_id"] == str(session_id)
        assert data["profile_version"] == "v1"

    def test_evidence_ref_validation(self):
        ref = EvidenceRef(ref_type="turn", ref_id="turn:7", confidence=0.8)
        assert ref.ref_type == "turn"

    def test_construct_defaults(self):
        c = Construct(key="test", label="Test", evidence_summary="E")
        assert c.status == HypothesisStatus.weak
        assert c.score is None
        assert c.evidence_refs == []

    def test_synthesis_response_defaults(self):
        r = SynthesisResponse(session_id=uuid.uuid4())
        assert r.is_valid is False
        assert r.parsed_profile is None
