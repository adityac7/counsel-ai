"""Cross-modal correlator — discovers reinforcements and contradictions across modalities.

Takes an evidence graph (nodes already populated by the graph builder) and
adds edges by matching signals that overlap in time (same turn or same topic window).

Correlation rules:
  1. **Time-aligned co-occurrence**: nodes sharing a turn_index or overlapping ms ranges.
  2. **Reinforcement**: two signals from different modalities pointing in the same direction
     (e.g., hedging text + vocal confidence drop → supports "uncertainty").
  3. **Contradiction**: two signals from different modalities pointing opposite ways
     (e.g., high-agency text + gaze aversion + low vocal confidence → contradicts "confidence").
  4. **Context linking**: topic window nodes are linked to all evidence within their range.

Output: the same EvidenceGraph, now enriched with edges.
"""

from __future__ import annotations

import logging
import uuid
from collections import defaultdict
from typing import Any

from counselai.analysis.evidence_graph import (
    EdgeRelation,
    EvidenceEdge,
    EvidenceGraph,
    EvidenceNode,
    NodeType,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Correlation rule definitions
# ---------------------------------------------------------------------------

# Signal pairs that reinforce each other when co-located
_REINFORCEMENT_RULES: list[dict[str, Any]] = [
    {
        "name": "hedging_plus_confidence_drop",
        "a_modality": "content", "a_signal": "hedging",
        "b_modality": "audio",  "b_signal": "confidence_drop",
        "reason": "Verbal hedging + vocal confidence drop → uncertainty signal reinforced",
    },
    {
        "name": "hedging_plus_pause",
        "a_modality": "content", "a_signal": "hedging",
        "b_modality": "audio",  "b_signal": "pause",
        "reason": "Hedging language near a significant pause → cognitive load or avoidance",
    },
    {
        "name": "avoidance_plus_gaze_aversion",
        "a_modality": "content", "a_signal": "avoidance",
        "b_modality": "video",  "b_signal": "gaze_aversion",
        "reason": "Topic avoidance + gaze aversion → discomfort with topic reinforced",
    },
    {
        "name": "avoidance_plus_tension",
        "a_modality": "content", "a_signal": "avoidance",
        "b_modality": "video",  "b_signal": "tension",
        "reason": "Topic avoidance + facial tension → emotional discomfort",
    },
    {
        "name": "avoidance_plus_pause",
        "a_modality": "content", "a_signal": "avoidance",
        "b_modality": "audio",  "b_signal": "pause",
        "reason": "Topic avoidance + significant pause → processing or reluctance",
    },
    {
        "name": "low_agency_plus_confidence_drop",
        "a_modality": "content", "a_signal": "agency",
        "b_modality": "audio",  "b_signal": "confidence_drop",
        "reason": "Low agency language + vocal confidence drop → diminished self-efficacy",
        "a_filter": lambda node: node.data.get("level") == "low",
    },
    {
        "name": "low_agency_plus_gaze_aversion",
        "a_modality": "content", "a_signal": "agency",
        "b_modality": "video",  "b_signal": "gaze_aversion",
        "reason": "Low agency + gaze aversion → withdrawal or deference",
        "a_filter": lambda node: node.data.get("level") == "low",
    },
    {
        "name": "code_switch_plus_speech_rate_change",
        "a_modality": "content", "a_signal": "code_switch",
        "b_modality": "audio",  "b_signal": "speech_rate_fast",
        "reason": "Code-switching + speech rate increase → emotional activation on topic",
    },
    {
        "name": "dysfluency_plus_tension",
        "a_modality": "audio", "a_signal": "dysfluency",
        "b_modality": "video", "b_signal": "tension",
        "reason": "Speech dysfluency + facial tension → anxiety signal across modalities",
    },
    {
        "name": "dysfluency_plus_fidgeting",
        "a_modality": "audio", "a_signal": "dysfluency",
        "b_modality": "video", "b_signal": "movement",
        "reason": "Speech dysfluency + body movement → nervousness reinforced",
        "b_filter": lambda node: node.data.get("type") == "fidgeting",
    },
    {
        "name": "confidence_drop_plus_gaze_aversion",
        "a_modality": "audio", "a_signal": "confidence_drop",
        "b_modality": "video", "b_signal": "gaze_aversion",
        "reason": "Vocal confidence drop + gaze aversion → lack of conviction",
    },
]

# Signal pairs that contradict each other
_CONTRADICTION_RULES: list[dict[str, Any]] = [
    {
        "name": "high_agency_but_low_confidence",
        "a_modality": "content", "a_signal": "agency",
        "b_modality": "audio",  "b_signal": "confidence_drop",
        "reason": "High agency language but vocal confidence dropped — possible performative assertion",
        "a_filter": lambda node: node.data.get("level") == "high",
    },
    {
        "name": "high_agency_but_gaze_aversion",
        "a_modality": "content", "a_signal": "agency",
        "b_modality": "video",  "b_signal": "gaze_aversion",
        "reason": "High agency text + gaze aversion → verbal assertion may not match internal state",
        "a_filter": lambda node: node.data.get("level") == "high",
    },
    {
        "name": "no_hedging_but_dysfluent",
        "a_modality": "audio", "a_signal": "dysfluency",
        "b_modality": "content", "b_signal": "agency",
        "reason": "Dysfluent speech despite assertive language → words outpacing confidence",
        "b_filter": lambda node: node.data.get("level") == "high",
    },
]

# Minimum time proximity (ms) for two events to be considered co-located
# when they don't share an exact turn index.
_TIME_PROXIMITY_MS = 5000


# ---------------------------------------------------------------------------
# Main correlator
# ---------------------------------------------------------------------------

def correlate(graph: EvidenceGraph) -> EvidenceGraph:
    """Run all correlation passes on an evidence graph and return it with edges added.

    Passes:
      1. Context linking (topic windows → contained evidence)
      2. Turn-aligned co-occurrence
      3. Rule-based reinforcement
      4. Rule-based contradiction
    """
    _link_windows_to_evidence(graph)
    _link_turn_co_occurrences(graph)
    _apply_rules(graph, _REINFORCEMENT_RULES, EdgeRelation.supports)
    _apply_rules(graph, _CONTRADICTION_RULES, EdgeRelation.contradicts)

    # Stats
    relation_counts = defaultdict(int)
    for e in graph.edges:
        relation_counts[e.relation.value] += 1
    logger.info(
        "Correlator finished for session %s: %d edges (%s)",
        graph.session_id,
        len(graph.edges),
        ", ".join(f"{k}={v}" for k, v in sorted(relation_counts.items())),
    )
    return graph


# ---------------------------------------------------------------------------
# Pass 1: Link topic windows to contained evidence
# ---------------------------------------------------------------------------

def _link_windows_to_evidence(graph: EvidenceGraph) -> None:
    """Create context_for edges from each topic window to evidence within its range."""
    window_nodes = graph.nodes_by_type(NodeType.topic_window)
    non_window_nodes = [n for n in graph.nodes if n.node_type != NodeType.topic_window]

    for wn in window_nodes:
        w_start = wn.start_ms or 0
        w_end = wn.end_ms or 0
        wid = wn.window_id or wn.id

        for en in non_window_nodes:
            if _node_in_range(en, w_start, w_end):
                graph.link(wn, en, EdgeRelation.context_for, weight=0.8,
                           reason=f"Evidence within topic window '{wn.label}'")
                # Also stamp the window_id on the evidence node if empty
                if en.window_id is None:
                    en.window_id = wid


def _node_in_range(node: EvidenceNode, start_ms: int, end_ms: int) -> bool:
    """Check if a node falls within a time range."""
    n_start = node.start_ms
    if n_start is not None:
        return start_ms <= n_start <= end_ms
    return False


# ---------------------------------------------------------------------------
# Pass 2: Turn-aligned co-occurrence
# ---------------------------------------------------------------------------

def _link_turn_co_occurrences(graph: EvidenceGraph) -> None:
    """Link nodes from different modalities that share the same turn index."""
    by_turn: dict[int, list[EvidenceNode]] = defaultdict(list)
    for n in graph.nodes:
        if n.turn_index is not None and n.node_type != NodeType.topic_window:
            by_turn[n.turn_index].append(n)

    for turn_idx, nodes in by_turn.items():
        if len(nodes) < 2:
            continue
        # Only link across modalities, avoid self-loops
        for i, a in enumerate(nodes):
            for b in nodes[i + 1:]:
                if a.modality != b.modality:
                    graph.link(
                        a, b, EdgeRelation.co_occurs, weight=0.6,
                        reason=f"Co-occur at turn {turn_idx}",
                    )


# ---------------------------------------------------------------------------
# Pass 3 & 4: Rule-based reinforcement / contradiction
# ---------------------------------------------------------------------------

def _apply_rules(
    graph: EvidenceGraph,
    rules: list[dict[str, Any]],
    relation: EdgeRelation,
) -> None:
    """Apply correlation rules to find matches and create edges."""
    for rule in rules:
        a_mod = rule["a_modality"]
        a_sig = rule["a_signal"]
        b_mod = rule["b_modality"]
        b_sig = rule["b_signal"]
        reason = rule["reason"]
        a_filter = rule.get("a_filter")
        b_filter = rule.get("b_filter")

        # Collect candidate nodes
        a_nodes = [
            n for n in graph.nodes
            if n.modality == a_mod
            and n.data.get("signal_key") == a_sig
            and (a_filter is None or a_filter(n))
        ]
        b_nodes = [
            n for n in graph.nodes
            if n.modality == b_mod
            and n.data.get("signal_key") == b_sig
            and (b_filter is None or b_filter(n))
        ]

        if not a_nodes or not b_nodes:
            continue

        for a in a_nodes:
            for b in b_nodes:
                if _are_proximate(a, b):
                    weight = _compute_edge_weight(a, b)
                    graph.link(a, b, relation, weight=weight, reason=reason)


def _are_proximate(a: EvidenceNode, b: EvidenceNode) -> bool:
    """Check if two nodes are temporally proximate (same turn or close in time)."""
    # Same turn is always proximate
    if a.turn_index is not None and a.turn_index == b.turn_index:
        return True

    # Adjacent turns count
    if (a.turn_index is not None and b.turn_index is not None
            and abs(a.turn_index - b.turn_index) <= 1):
        return True

    # Timestamp proximity
    a_ms = a.start_ms
    b_ms = b.start_ms
    if a_ms is not None and b_ms is not None:
        return abs(a_ms - b_ms) <= _TIME_PROXIMITY_MS

    return False


def _compute_edge_weight(a: EvidenceNode, b: EvidenceNode) -> float:
    """Compute edge weight from the confidence of both endpoints."""
    avg_conf = (a.confidence + b.confidence) / 2.0

    # Same turn gets a boost
    same_turn_bonus = 0.1 if (a.turn_index is not None and a.turn_index == b.turn_index) else 0.0

    return round(min(1.0, avg_conf + same_turn_bonus), 3)
