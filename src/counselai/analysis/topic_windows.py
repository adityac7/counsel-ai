"""Topic window builder — groups turns into topic-based time windows.

A topic window is a contiguous (or near-contiguous) stretch of the
conversation where a particular topic is being discussed. These windows
are the primary alignment unit for cross-modal signal correlation.

Input: ContentFeatures (from the content extractor)
Output: list[TopicWindow] (written to signal_windows DB table)
"""

from __future__ import annotations

import logging
import uuid
from typing import Sequence

from counselai.signals.common.schemas import TopicWindow
from counselai.signals.content.extractor import CanonicalTurn
from counselai.signals.content.schemas import ContentFeatures, TopicMention

logger = logging.getLogger(__name__)

# Maximum gap (in turns) between mentions of the same topic before
# we split into separate windows.
_MAX_TURN_GAP = 3


def build_topic_windows(
    session_id: uuid.UUID,
    features: ContentFeatures,
    turns: Sequence[CanonicalTurn],
) -> list[TopicWindow]:
    """Build topic windows from content features and canonical turns.

    Algorithm:
      1. For each topic in features.topics, get its turn_indices.
      2. Sort turn indices and split into contiguous groups
         (allowing gaps of up to _MAX_TURN_GAP turns).
      3. For each group, compute start_ms/end_ms from the actual turns.
      4. Create a TopicWindow with reliability from the topic confidence.
    """
    if not features.topics or not turns:
        return []

    # Build turn index → turn lookup
    turn_map: dict[int, CanonicalTurn] = {t.turn_index: t for t in turns}

    windows: list[TopicWindow] = []

    for topic in features.topics:
        if not topic.turn_indices:
            continue

        groups = _split_into_groups(sorted(topic.turn_indices))

        for group in groups:
            # Resolve timing from actual turns
            start_ms = _resolve_start_ms(group, turn_map)
            end_ms = _resolve_end_ms(group, turn_map)

            if start_ms is None or end_ms is None:
                continue

            window = TopicWindow(
                session_id=session_id,
                topic_key=topic.topic_key,
                start_ms=start_ms,
                end_ms=end_ms,
                source_turn_indices=group,
                reliability_score=_window_reliability(topic, group, turn_map),
            )
            windows.append(window)

    # Sort by start time
    windows.sort(key=lambda w: w.start_ms)

    logger.info(
        "Built %d topic windows for session %s from %d topics",
        len(windows), session_id, len(features.topics),
    )
    return windows


def _split_into_groups(indices: list[int]) -> list[list[int]]:
    """Split sorted turn indices into contiguous groups.

    Two consecutive indices are in the same group if their gap
    is ≤ _MAX_TURN_GAP.
    """
    if not indices:
        return []

    groups: list[list[int]] = [[indices[0]]]

    for i in range(1, len(indices)):
        if indices[i] - indices[i - 1] <= _MAX_TURN_GAP:
            groups[-1].append(indices[i])
        else:
            groups.append([indices[i]])

    return groups


def _resolve_start_ms(
    group: list[int],
    turn_map: dict[int, CanonicalTurn],
) -> int | None:
    """Get the start_ms of the earliest turn in a group."""
    for idx in group:
        if idx in turn_map:
            return turn_map[idx].start_ms
    return None


def _resolve_end_ms(
    group: list[int],
    turn_map: dict[int, CanonicalTurn],
) -> int | None:
    """Get the end_ms of the latest turn in a group."""
    for idx in reversed(group):
        if idx in turn_map:
            return turn_map[idx].end_ms
    return None


def _window_reliability(
    topic: TopicMention,
    group: list[int],
    turn_map: dict[int, CanonicalTurn],
) -> float:
    """Compute reliability for a single topic window.

    Factors:
    - Topic extraction confidence (from LLM)
    - Number of turns in the window (more = more reliable)
    - Whether the turns actually exist in turn_map
    """
    base = topic.confidence

    # Turn count bonus: 1 turn = 0.0, 3+ turns = 0.2 bonus
    count_bonus = min(0.2, (len(group) - 1) * 0.1)

    # Coverage penalty: if turns are missing from map
    found = sum(1 for idx in group if idx in turn_map)
    coverage = found / len(group) if group else 0.0

    reliability = base * coverage + count_bonus
    return round(min(1.0, max(0.0, reliability)), 3)


# ---------------------------------------------------------------------------
# Convenience: convert windows to signal observations
# ---------------------------------------------------------------------------

def windows_to_observations(
    windows: list[TopicWindow],
    features: ContentFeatures,
) -> list[dict]:
    """Convert topic windows + content features into flat signal observations.

    Returns dicts ready for SignalObservation creation. This bridges the
    content extractor output to the unified signal_observations table.
    """
    from counselai.signals.common.schemas import Modality, ObservationSource

    observations: list[dict] = []
    session_id = features.session_id

    # Build window lookup by topic_key for linking
    window_by_topic: dict[str, list[TopicWindow]] = {}
    for w in windows:
        window_by_topic.setdefault(w.topic_key, []).append(w)

    # Hedging observations
    for h in features.hedging_markers:
        observations.append({
            "session_id": session_id,
            "window_id": _find_window_id(h.turn_index, window_by_topic),
            "turn_index": h.turn_index,
            "modality": Modality.content,
            "signal_key": "hedging",
            "value_json": {
                "text": h.text,
                "hedge_type": h.hedge_type,
            },
            "confidence": h.confidence,
            "source": ObservationSource.deterministic if h.confidence >= 0.7 else ObservationSource.llm_extracted,
            "evidence_ref_json": {"turn_index": h.turn_index},
        })

    # Agency observations
    for a in features.agency_markers:
        observations.append({
            "session_id": session_id,
            "window_id": _find_window_id(a.turn_index, window_by_topic),
            "turn_index": a.turn_index,
            "modality": Modality.content,
            "signal_key": "agency",
            "value_json": {
                "text": a.text,
                "level": a.level.value,
                "direction": a.direction,
            },
            "confidence": a.confidence,
            "source": ObservationSource.deterministic if a.confidence >= 0.7 else ObservationSource.llm_extracted,
            "evidence_ref_json": {"turn_index": a.turn_index},
        })

    # Avoidance observations
    for av in features.avoidance_events:
        observations.append({
            "session_id": session_id,
            "window_id": _find_window_id(av.turn_index, window_by_topic),
            "turn_index": av.turn_index,
            "modality": Modality.content,
            "signal_key": "avoidance",
            "value_json": {
                "topic_key": av.topic_key,
                "trigger_text": av.trigger_text,
                "avoidance_text": av.avoidance_text,
            },
            "confidence": av.confidence,
            "source": ObservationSource.llm_extracted,
            "evidence_ref_json": {"turn_index": av.turn_index, "topic_key": av.topic_key},
        })

    # Code-switch observations
    for cs in features.code_switch_events:
        observations.append({
            "session_id": session_id,
            "window_id": _find_window_id(cs.turn_index, window_by_topic),
            "turn_index": cs.turn_index,
            "modality": Modality.content,
            "signal_key": "code_switch",
            "value_json": {
                "direction": cs.direction.value,
                "trigger_context": cs.trigger_context,
                "text_before": cs.text_before,
                "text_after": cs.text_after,
            },
            "confidence": cs.confidence,
            "source": ObservationSource.deterministic if cs.confidence >= 0.7 else ObservationSource.llm_extracted,
            "evidence_ref_json": {"turn_index": cs.turn_index},
        })

    return observations


def _find_window_id(
    turn_index: int,
    window_by_topic: dict[str, list[TopicWindow]],
) -> uuid.UUID | None:
    """Find the first topic window that contains a given turn index."""
    for windows in window_by_topic.values():
        for w in windows:
            if turn_index in w.source_turn_indices:
                return w.id
    return None
