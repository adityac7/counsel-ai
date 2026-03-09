"""Unit tests for the content signal extractor (deterministic layer) and topic windows."""

import uuid

import pytest

from counselai.signals.content.extractor import (
    CanonicalTurn,
    _detect_hedging_deterministic,
    _detect_agency_deterministic,
    _detect_code_switching,
    _estimate_dominant_language,
)
from counselai.signals.content.schemas import (
    AgencyLevel,
    CodeSwitchDirection,
    ContentFeatures,
    TopicDepth,
    TopicMention,
)
from counselai.analysis.topic_windows import (
    build_topic_windows,
    _split_into_groups,
    windows_to_observations,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _student_turn(index: int, text: str, start_ms: int = 0, end_ms: int = 1000) -> CanonicalTurn:
    return CanonicalTurn(
        turn_index=index, speaker="student", text=text,
        start_ms=start_ms, end_ms=end_ms,
    )

def _counsellor_turn(index: int, text: str) -> CanonicalTurn:
    return CanonicalTurn(turn_index=index, speaker="counsellor", text=text)


# ---------------------------------------------------------------------------
# Hedging detection
# ---------------------------------------------------------------------------

class TestHedgingDetection:
    def test_english_hedges(self):
        turn = _student_turn(0, "I think maybe I should study engineering")
        markers = _detect_hedging_deterministic(turn)
        texts = [m.text.lower() for m in markers]
        assert any("i think" in t for t in texts)

    def test_hindi_hedges(self):
        turn = _student_turn(0, "Shayad mujhe lagta hai ki engineering better hai")
        markers = _detect_hedging_deterministic(turn)
        texts = [m.text.lower() for m in markers]
        assert any("shayad" in t for t in texts)
        assert any("lagta hai" in t or "mujhe lagta" in t for t in texts)

    def test_no_hedges_in_confident_speech(self):
        turn = _student_turn(0, "I will study computer science")
        markers = _detect_hedging_deterministic(turn)
        assert len(markers) == 0

    def test_counsellor_turns_ignored(self):
        turn = _counsellor_turn(0, "I think you should explore this more")
        markers = _detect_hedging_deterministic(turn)
        assert len(markers) == 0

    def test_hedge_type_classification(self):
        turn = _student_turn(0, "I don't know, maybe it's fine, basically whatever")
        markers = _detect_hedging_deterministic(turn)
        types = {m.hedge_type for m in markers}
        # Should have qualifier (maybe), filler (basically), disclaimer (I don't know)
        assert len(types) >= 2


# ---------------------------------------------------------------------------
# Agency detection
# ---------------------------------------------------------------------------

class TestAgencyDetection:
    def test_high_agency_english(self):
        turn = _student_turn(0, "I want to become a doctor and I will work hard for it")
        markers = _detect_agency_deterministic(turn)
        assert any(m.level == AgencyLevel.high for m in markers)

    def test_low_agency_english(self):
        turn = _student_turn(0, "My parents decide everything, I have to follow them")
        markers = _detect_agency_deterministic(turn)
        assert any(m.level == AgencyLevel.low for m in markers)

    def test_low_agency_hindi(self):
        turn = _student_turn(0, "Ghar wale jo bolen wahi karna padta hai, majboor hun")
        markers = _detect_agency_deterministic(turn)
        assert any(m.level == AgencyLevel.low for m in markers)

    def test_direction_detection(self):
        turn = _student_turn(0, "Family pressure is too much, parents decide")
        markers = _detect_agency_deterministic(turn)
        parent_markers = [m for m in markers if m.direction == "parent"]
        assert len(parent_markers) > 0


# ---------------------------------------------------------------------------
# Code-switching detection
# ---------------------------------------------------------------------------

class TestCodeSwitching:
    def test_devanagari_latin_mix(self):
        # Devanagari + Latin in same turn = code switch
        turn = _student_turn(0, "मुझे लगता है कि engineering is better than arts")
        events = _detect_code_switching(turn)
        assert len(events) == 1
        assert events[0].direction == CodeSwitchDirection.hindi_to_english

    def test_pure_english_no_switch(self):
        turn = _student_turn(0, "I want to study computer science")
        events = _detect_code_switching(turn)
        assert len(events) == 0

    def test_counsellor_ignored(self):
        turn = _counsellor_turn(0, "बेटा, tell me more about this")
        events = _detect_code_switching(turn)
        assert len(events) == 0


# ---------------------------------------------------------------------------
# Language estimation
# ---------------------------------------------------------------------------

class TestLanguageEstimation:
    def test_english_dominant(self):
        turns = [_student_turn(i, f"I like studying science and math subject {i}") for i in range(5)]
        assert _estimate_dominant_language(turns) == "en"

    def test_hindi_dominant(self):
        turns = [_student_turn(i, "मुझे विज्ञान पसंद है") for i in range(5)]
        assert _estimate_dominant_language(turns) == "hi"

    def test_hinglish(self):
        turns = [_student_turn(0, "मुझे लगता है engineering is good for future")]
        assert _estimate_dominant_language(turns) == "hinglish"


# ---------------------------------------------------------------------------
# Topic window builder
# ---------------------------------------------------------------------------

class TestTopicWindows:
    def test_split_into_groups_contiguous(self):
        groups = _split_into_groups([1, 2, 3, 4])
        assert groups == [[1, 2, 3, 4]]

    def test_split_into_groups_with_gap(self):
        groups = _split_into_groups([1, 2, 8, 9])
        assert len(groups) == 2
        assert groups[0] == [1, 2]
        assert groups[1] == [8, 9]

    def test_split_into_groups_within_max_gap(self):
        # Gap of 3 is within _MAX_TURN_GAP=3
        groups = _split_into_groups([1, 4])
        assert groups == [[1, 4]]

    def test_build_windows_basic(self):
        session_id = uuid.uuid4()
        turns = [
            _student_turn(0, "I like science", start_ms=0, end_ms=5000),
            _counsellor_turn(1, "Tell me more"),
            _student_turn(2, "Science is fun", start_ms=6000, end_ms=10000),
        ]
        features = ContentFeatures(
            session_id=session_id,
            topics=[
                TopicMention(
                    topic_key="career_interest",
                    label="Career Interest",
                    depth=TopicDepth.moderate,
                    turn_indices=[0, 2],
                    confidence=0.8,
                )
            ],
        )
        windows = build_topic_windows(session_id, features, turns)
        assert len(windows) == 1
        assert windows[0].topic_key == "career_interest"
        assert windows[0].start_ms == 0
        assert windows[0].end_ms == 10000

    def test_build_windows_empty(self):
        session_id = uuid.uuid4()
        features = ContentFeatures(session_id=session_id)
        windows = build_topic_windows(session_id, features, [])
        assert windows == []

    def test_windows_to_observations(self):
        session_id = uuid.uuid4()
        features = ContentFeatures(
            session_id=session_id,
            hedging_markers=[
                _create_hedging_marker(turn_index=0, text="maybe"),
            ],
            agency_markers=[
                _create_agency_marker(turn_index=2, text="I want to"),
            ],
        )
        obs = windows_to_observations([], features)
        assert len(obs) == 2
        signal_keys = {o["signal_key"] for o in obs}
        assert "hedging" in signal_keys
        assert "agency" in signal_keys


# Helpers for observation tests
def _create_hedging_marker(**kwargs):
    from counselai.signals.content.schemas import HedgingMarker
    return HedgingMarker(**kwargs)

def _create_agency_marker(**kwargs):
    from counselai.signals.content.schemas import AgencyMarker
    return AgencyMarker(**kwargs)
