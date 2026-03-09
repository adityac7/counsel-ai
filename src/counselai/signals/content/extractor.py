"""Content signal extractor — deterministic + LLM-assisted analysis.

Takes canonical turns and produces structured content features:
topics, avoidance events, hedging markers, agency markers, and
code-switching events.

Two-layer approach:
  1. Deterministic: regex/keyword hedging, Unicode-based code-switching,
     basic agency keyword scanning.
  2. LLM-assisted: Gemini structured extraction for topics, avoidance,
     depth scoring, and nuanced agency/hedging that keywords miss.

The deterministic layer runs first, then the LLM layer enriches.
Final output merges both, deduplicating by turn index.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from typing import Any, Sequence

from counselai.live.providers.base import SynthesisProviderBase, SynthesisRequest
from counselai.signals.content.schemas import (
    AgencyLevel,
    AgencyMarker,
    AvoidanceEvent,
    CodeSwitchDirection,
    CodeSwitchEvent,
    ContentFeatures,
    HedgingMarker,
    TopicDepth,
    TopicMention,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Canonical turn input
# ---------------------------------------------------------------------------

@dataclass
class CanonicalTurn:
    """Minimal turn representation for the content extractor."""
    turn_index: int
    speaker: str  # "student", "counsellor", "system"
    text: str
    start_ms: int = 0
    end_ms: int = 0
    confidence: float | None = None


# ---------------------------------------------------------------------------
# Deterministic detectors
# ---------------------------------------------------------------------------

# Hindi hedging phrases (Hinglish/Hindi)
_HINDI_HEDGES = [
    r"\bshayad\b", r"\blagta hai\b", r"\bmujhe lagta\b",
    r"\bpata nahi\b", r"\bho sakta\b", r"\bkuch kuch\b",
    r"\baise hi\b", r"\bthoda\b", r"\bkya pata\b",
    r"\bsamajh nahi\b", r"\bmaybe\b",
]

# English hedging phrases
_ENGLISH_HEDGES = [
    r"\bi think\b", r"\bi guess\b", r"\bmaybe\b", r"\bprobably\b",
    r"\bkind of\b", r"\bsort of\b", r"\bi mean\b", r"\blike\b,",
    r"\bi don'?t know\b", r"\bnot sure\b", r"\bperhaps\b",
    r"\bmight be\b", r"\bcould be\b", r"\bi suppose\b",
    r"\bjust\b", r"\bbasically\b",
]

_HEDGE_PATTERNS: list[re.Pattern] = [
    re.compile(p, re.IGNORECASE) for p in _HINDI_HEDGES + _ENGLISH_HEDGES
]

# Hedge type classification
_QUALIFIER_WORDS = {"shayad", "maybe", "probably", "perhaps", "might", "could", "ho sakta"}
_FILLER_WORDS = {"like", "basically", "just", "i mean", "aise hi"}
_DISCLAIMER_WORDS = {"i don't know", "pata nahi", "not sure", "samajh nahi", "i guess"}


def _classify_hedge(text: str) -> str:
    lower = text.lower().strip()
    for w in _QUALIFIER_WORDS:
        if w in lower:
            return "qualifier"
    for w in _FILLER_WORDS:
        if w in lower:
            return "filler"
    for w in _DISCLAIMER_WORDS:
        if w in lower:
            return "disclaimer"
    return "general"


# Agency keywords
_HIGH_AGENCY = [
    r"\bi want\b", r"\bi will\b", r"\bi'?m going to\b",
    r"\bmy decision\b", r"\bi choose\b", r"\bi decided\b",
    r"\bmain.*karunga\b", r"\bmain.*chahta\b", r"\bmera faisla\b",
    r"\bmain.*karna\b", r"\bi plan\b",
]
_LOW_AGENCY = [
    r"\bparents.*decide\b", r"\bwhatever.*say\b",
    r"\bthey want\b", r"\bi have to\b", r"\bno choice\b",
    r"\bunke hisaab se\b", r"\bjo.*bolen\b", r"\bmajboor\b",
    r"\bmujhe.*karna padega\b", r"\bghar.*wale\b",
    r"\bfamily pressure\b", r"\bwhat.*others think\b",
]

_HIGH_AGENCY_PATTERNS = [re.compile(p, re.IGNORECASE) for p in _HIGH_AGENCY]
_LOW_AGENCY_PATTERNS = [re.compile(p, re.IGNORECASE) for p in _LOW_AGENCY]

# Unicode ranges for Hindi (Devanagari)
_DEVANAGARI_RE = re.compile(r"[\u0900-\u097F]")
_LATIN_WORD_RE = re.compile(r"[a-zA-Z]{2,}")


def _detect_hedging_deterministic(turn: CanonicalTurn) -> list[HedgingMarker]:
    """Find hedging markers via regex in a single turn."""
    if turn.speaker != "student":
        return []
    markers = []
    for pat in _HEDGE_PATTERNS:
        for m in pat.finditer(turn.text):
            markers.append(HedgingMarker(
                turn_index=turn.turn_index,
                start_ms=turn.start_ms,
                end_ms=turn.end_ms,
                text=m.group(0),
                hedge_type=_classify_hedge(m.group(0)),
                confidence=0.7,
            ))
    return markers


def _detect_agency_deterministic(turn: CanonicalTurn) -> list[AgencyMarker]:
    """Find agency markers via regex."""
    if turn.speaker != "student":
        return []
    markers = []
    for pat in _HIGH_AGENCY_PATTERNS:
        for m in pat.finditer(turn.text):
            markers.append(AgencyMarker(
                turn_index=turn.turn_index,
                text=m.group(0),
                level=AgencyLevel.high,
                direction="self",
                confidence=0.65,
            ))
    for pat in _LOW_AGENCY_PATTERNS:
        for m in pat.finditer(turn.text):
            markers.append(AgencyMarker(
                turn_index=turn.turn_index,
                text=m.group(0),
                level=AgencyLevel.low,
                direction="parent" if any(w in m.group(0).lower() for w in ("parent", "ghar", "family")) else "authority",
                confidence=0.65,
            ))
    return markers


def _detect_code_switching(turn: CanonicalTurn) -> list[CodeSwitchEvent]:
    """Detect Hindi↔English code-switching within a turn using Unicode heuristics."""
    if turn.speaker != "student":
        return []

    text = turn.text
    has_devanagari = bool(_DEVANAGARI_RE.search(text))
    latin_words = _LATIN_WORD_RE.findall(text)
    has_latin = len(latin_words) > 1  # at least 2 Latin words

    # Hinglish romanization detection: Hindi words in Latin script
    # We detect by looking for segments — if the text is purely one script, no switch.
    if not (has_devanagari and has_latin):
        return []

    # There's a mix of Devanagari and Latin — that's a code-switch event
    # Determine direction by which script comes first
    first_dev = _DEVANAGARI_RE.search(text)
    first_lat = _LATIN_WORD_RE.search(text)

    if first_dev and first_lat:
        if first_dev.start() < first_lat.start():
            direction = CodeSwitchDirection.hindi_to_english
        else:
            direction = CodeSwitchDirection.english_to_hindi
    else:
        direction = CodeSwitchDirection.other

    return [CodeSwitchEvent(
        turn_index=turn.turn_index,
        start_ms=turn.start_ms,
        end_ms=turn.end_ms,
        direction=direction,
        trigger_context=None,
        text_before=text[:50],
        text_after=text[50:100] if len(text) > 50 else "",
        confidence=0.6,
    )]


def _estimate_dominant_language(turns: Sequence[CanonicalTurn]) -> str:
    """Estimate dominant language from student turns."""
    devanagari_chars = 0
    latin_chars = 0
    for t in turns:
        if t.speaker != "student":
            continue
        devanagari_chars += len(_DEVANAGARI_RE.findall(t.text))
        latin_chars += len(_LATIN_WORD_RE.findall(t.text))

    if devanagari_chars > 0 and latin_chars > 0:
        return "hinglish"
    elif devanagari_chars > latin_chars:
        return "hi"
    else:
        return "en"


# ---------------------------------------------------------------------------
# LLM extraction prompts
# ---------------------------------------------------------------------------

_CONTENT_EXTRACTION_SYSTEM = """You are an expert counselling session analyst specializing in Indian school students (classes 9-12). You analyze conversation transcripts between a student and a counsellor.

Your task: Extract structured signals from the transcript. Be precise and evidence-based. Do NOT infer beyond what the text supports.

The conversation may be in English, Hindi, or Hinglish (a mix). Handle all three naturally."""

_CONTENT_EXTRACTION_PROMPT = """Analyze this counselling session transcript and extract ALL of the following signals. Return valid JSON only.

## TRANSCRIPT
{transcript}

## EXTRACT THE FOLLOWING

Return a JSON object with these keys:

### "topics" — array of topics discussed
Each topic: {{"topic_key": "snake_case_id", "label": "Human Name", "depth": "surface|moderate|deep", "turn_indices": [int], "confidence": 0.0-1.0}}

Common counselling topics: career_interest, academic_pressure, peer_relationships, family_dynamics, self_awareness, emotional_regulation, decision_making, values_exploration, future_planning, extracurricular, social_media, mental_health, identity, authority_relationships

### "avoidance_events" — array of moments where the student avoids/deflects a topic
Each: {{"topic_key": "str", "turn_index": int, "trigger_text": "what prompted it", "avoidance_text": "the deflecting response", "confidence": 0.0-1.0}}

Signs of avoidance: topic changes, vague responses to specific questions, nervous laughter markers, "I don't know" when they clearly have opinions, redirecting to safer topics

### "hedging_markers" — array of hedging/uncertainty expressions BY THE STUDENT
Each: {{"turn_index": int, "text": "the hedging phrase", "hedge_type": "general|qualifier|filler|disclaimer", "confidence": 0.0-1.0}}

### "agency_markers" — array of self-agency or external-agency expressions BY THE STUDENT
Each: {{"turn_index": int, "text": "the phrase", "level": "low|moderate|high", "direction": "self|parent|peer|authority", "confidence": 0.0-1.0}}

High agency: "I want to...", "I decided...", "Main karunga..."
Low agency: "Parents decide...", "Jo bolen...", "I have to..."

### "code_switch_events" — array of language switches BY THE STUDENT
Each: {{"turn_index": int, "direction": "hindi_to_english|english_to_hindi|other", "trigger_context": "what was being discussed", "text_before": "text in first language", "text_after": "text in second language", "confidence": 0.0-1.0}}

### "overall_depth" — "surface", "moderate", or "deep"
### "overall_agency" — "low", "moderate", or "high"

Return ONLY valid JSON. No markdown, no explanation."""


def _build_transcript_text(turns: Sequence[CanonicalTurn]) -> str:
    """Format turns into a readable transcript for the LLM."""
    lines = []
    for t in turns:
        speaker = "Student" if t.speaker == "student" else "Counsellor"
        lines.append(f"[Turn {t.turn_index}] {speaker}: {t.text}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main extractor
# ---------------------------------------------------------------------------

class ContentSignalExtractor:
    """Two-layer content signal extraction: deterministic + LLM.

    Usage:
        extractor = ContentSignalExtractor(synthesis_provider)
        features = await extractor.extract(session_id, turns)
    """

    def __init__(self, synthesis: SynthesisProviderBase) -> None:
        self._synthesis = synthesis

    async def extract(
        self,
        session_id: uuid.UUID,
        turns: Sequence[CanonicalTurn],
    ) -> ContentFeatures:
        """Run full content extraction pipeline.

        1. Deterministic pass (hedging, agency, code-switching)
        2. LLM pass (topics, avoidance, enriched hedging/agency/code-switching)
        3. Merge and deduplicate
        4. Compute reliability score
        """
        student_turns = [t for t in turns if t.speaker == "student"]

        if not student_turns:
            logger.warning("No student turns for session %s — returning empty features", session_id)
            return ContentFeatures(
                session_id=session_id,
                reliability_score=0.0,
            )

        # -- Layer 1: Deterministic -----------------------------------------
        det_hedging: list[HedgingMarker] = []
        det_agency: list[AgencyMarker] = []
        det_code_switch: list[CodeSwitchEvent] = []

        for turn in turns:
            det_hedging.extend(_detect_hedging_deterministic(turn))
            det_agency.extend(_detect_agency_deterministic(turn))
            det_code_switch.extend(_detect_code_switching(turn))

        dominant_lang = _estimate_dominant_language(turns)

        # -- Layer 2: LLM extraction ----------------------------------------
        llm_result = await self._extract_via_llm(turns)

        # -- Merge ----------------------------------------------------------
        topics = llm_result.get("topics", [])
        avoidance = llm_result.get("avoidance_events", [])
        llm_hedging = llm_result.get("hedging_markers", [])
        llm_agency = llm_result.get("agency_markers", [])
        llm_code_switch = llm_result.get("code_switch_events", [])
        overall_depth = llm_result.get("overall_depth", "surface")
        overall_agency = llm_result.get("overall_agency", "moderate")

        # Parse LLM output into schema objects
        topic_mentions = self._parse_topics(topics)
        avoidance_events = self._parse_avoidance(avoidance)
        hedging_markers = self._merge_hedging(det_hedging, llm_hedging)
        agency_markers = self._merge_agency(det_agency, llm_agency)
        code_switch_events = self._merge_code_switch(det_code_switch, llm_code_switch)

        # Reliability: based on transcript quality and turn count
        reliability = self._compute_reliability(turns, topic_mentions)

        return ContentFeatures(
            session_id=session_id,
            topics=topic_mentions,
            avoidance_events=avoidance_events,
            hedging_markers=hedging_markers,
            agency_markers=agency_markers,
            code_switch_events=code_switch_events,
            dominant_language=dominant_lang,
            overall_depth=TopicDepth(overall_depth) if overall_depth in TopicDepth.__members__ else TopicDepth.surface,
            overall_agency=AgencyLevel(overall_agency) if overall_agency in AgencyLevel.__members__ else AgencyLevel.moderate,
            reliability_score=reliability,
        )

    # -- LLM call -----------------------------------------------------------

    async def _extract_via_llm(self, turns: Sequence[CanonicalTurn]) -> dict[str, Any]:
        """Call Gemini for structured content extraction."""
        transcript = _build_transcript_text(turns)
        prompt = _CONTENT_EXTRACTION_PROMPT.format(transcript=transcript)

        try:
            response = await self._synthesis.generate(SynthesisRequest(
                system_prompt=_CONTENT_EXTRACTION_SYSTEM,
                user_prompt=prompt,
                temperature=0.15,
                max_tokens=8192,
            ))

            text = response.text.strip()
            # Strip markdown code fences if present
            if text.startswith("```"):
                text = re.sub(r"^```(?:json)?\s*", "", text)
                text = re.sub(r"\s*```$", "", text)

            result = json.loads(text)
            logger.info(
                "LLM content extraction complete: %d topics, %d avoidance, usage=%s",
                len(result.get("topics", [])),
                len(result.get("avoidance_events", [])),
                response.usage,
            )
            return result

        except json.JSONDecodeError as e:
            logger.error("LLM returned invalid JSON: %s", e)
            return {}
        except Exception:
            logger.exception("LLM content extraction failed")
            return {}

    # -- Parsers ------------------------------------------------------------

    def _parse_topics(self, raw: list[dict]) -> list[TopicMention]:
        results = []
        for item in raw:
            try:
                results.append(TopicMention(
                    topic_key=item["topic_key"],
                    label=item.get("label", item["topic_key"].replace("_", " ").title()),
                    depth=TopicDepth(item.get("depth", "surface")),
                    turn_indices=item.get("turn_indices", []),
                    confidence=float(item.get("confidence", 0.5)),
                ))
            except (KeyError, ValueError) as e:
                logger.debug("Skipping malformed topic: %s — %s", item, e)
        return results

    def _parse_avoidance(self, raw: list[dict]) -> list[AvoidanceEvent]:
        results = []
        for item in raw:
            try:
                results.append(AvoidanceEvent(
                    topic_key=item["topic_key"],
                    turn_index=int(item["turn_index"]),
                    trigger_text=item.get("trigger_text", ""),
                    avoidance_text=item.get("avoidance_text", ""),
                    confidence=float(item.get("confidence", 0.5)),
                ))
            except (KeyError, ValueError, TypeError) as e:
                logger.debug("Skipping malformed avoidance event: %s — %s", item, e)
        return results

    def _merge_hedging(
        self,
        deterministic: list[HedgingMarker],
        llm_raw: list[dict],
    ) -> list[HedgingMarker]:
        """Merge deterministic and LLM hedging markers, dedup by (turn_index, text)."""
        seen: set[tuple[int, str]] = set()
        merged: list[HedgingMarker] = []

        # Deterministic first (higher precision)
        for m in deterministic:
            key = (m.turn_index, m.text.lower().strip())
            if key not in seen:
                seen.add(key)
                merged.append(m)

        # LLM additions
        for item in llm_raw:
            try:
                turn_idx = int(item["turn_index"])
                text = item.get("text", "")
                key = (turn_idx, text.lower().strip())
                if key not in seen:
                    seen.add(key)
                    merged.append(HedgingMarker(
                        turn_index=turn_idx,
                        text=text,
                        hedge_type=item.get("hedge_type", "general"),
                        confidence=float(item.get("confidence", 0.6)),
                    ))
            except (KeyError, ValueError, TypeError):
                continue

        return merged

    def _merge_agency(
        self,
        deterministic: list[AgencyMarker],
        llm_raw: list[dict],
    ) -> list[AgencyMarker]:
        """Merge deterministic and LLM agency markers."""
        seen: set[tuple[int, str]] = set()
        merged: list[AgencyMarker] = []

        for m in deterministic:
            key = (m.turn_index, m.text.lower().strip())
            if key not in seen:
                seen.add(key)
                merged.append(m)

        for item in llm_raw:
            try:
                turn_idx = int(item["turn_index"])
                text = item.get("text", "")
                key = (turn_idx, text.lower().strip())
                if key not in seen:
                    seen.add(key)
                    merged.append(AgencyMarker(
                        turn_index=turn_idx,
                        text=text,
                        level=AgencyLevel(item.get("level", "moderate")),
                        direction=item.get("direction", "self"),
                        confidence=float(item.get("confidence", 0.6)),
                    ))
            except (KeyError, ValueError, TypeError):
                continue

        return merged

    def _merge_code_switch(
        self,
        deterministic: list[CodeSwitchEvent],
        llm_raw: list[dict],
    ) -> list[CodeSwitchEvent]:
        """Merge code-switch events, dedup by turn_index."""
        seen_turns: set[int] = set()
        merged: list[CodeSwitchEvent] = []

        for e in deterministic:
            if e.turn_index not in seen_turns:
                seen_turns.add(e.turn_index)
                merged.append(e)

        for item in llm_raw:
            try:
                turn_idx = int(item["turn_index"])
                if turn_idx not in seen_turns:
                    seen_turns.add(turn_idx)
                    direction = item.get("direction", "other")
                    merged.append(CodeSwitchEvent(
                        turn_index=turn_idx,
                        direction=CodeSwitchDirection(direction) if direction in CodeSwitchDirection.__members__ else CodeSwitchDirection.other,
                        trigger_context=item.get("trigger_context"),
                        text_before=item.get("text_before", ""),
                        text_after=item.get("text_after", ""),
                        confidence=float(item.get("confidence", 0.6)),
                    ))
            except (KeyError, ValueError, TypeError):
                continue

        return merged

    # -- Reliability --------------------------------------------------------

    def _compute_reliability(
        self,
        turns: Sequence[CanonicalTurn],
        topics: list[TopicMention],
    ) -> float:
        """Compute content extraction reliability score.

        Factors:
        - Turn count (more turns → more reliable)
        - Average turn length (very short turns = less signal)
        - Transcript confidence (low ASR confidence = less reliable)
        - Topic coverage (found topics = extraction worked)
        """
        student_turns = [t for t in turns if t.speaker == "student"]
        if not student_turns:
            return 0.0

        # Turn count factor: 0.3 at 1 turn, 1.0 at 8+ turns
        count_score = min(1.0, len(student_turns) / 8.0)

        # Average length factor
        avg_len = sum(len(t.text) for t in student_turns) / len(student_turns)
        length_score = min(1.0, avg_len / 50.0)  # 50 chars = decent turn

        # Confidence factor (from ASR)
        confidences = [t.confidence for t in student_turns if t.confidence is not None]
        conf_score = sum(confidences) / len(confidences) if confidences else 0.7

        # Topic factor
        topic_score = min(1.0, len(topics) / 3.0) if topics else 0.3

        # Weighted combination
        reliability = (
            0.3 * count_score
            + 0.2 * length_score
            + 0.3 * conf_score
            + 0.2 * topic_score
        )
        return round(min(1.0, max(0.0, reliability)), 3)
