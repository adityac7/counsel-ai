"""Hypothesis generator and ranker — produces evidence-backed hypotheses from the graph.

A hypothesis is a bounded claim about a psychological construct
(e.g., "career identity clarity", "external pressure", "emotional regulation")
that is backed by specific evidence nodes and edges.

The ranker walks the evidence graph, groups evidence by construct, weighs
supporting vs. contradicting edges, and outputs ranked hypotheses with
explicit evidence references.

Output maps to the `hypotheses` DB table and is persisted in:
  artifacts/sessions/<session_id>/analysis/evidence-graph.json (as part of the graph)
"""

from __future__ import annotations

import logging
import uuid
from enum import Enum

from pydantic import BaseModel, Field

from counselai.analysis.evidence_graph import (
    EdgeRelation,
    EvidenceGraph,
    EvidenceNode,
    NodeType,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

class HypothesisStatus(str, Enum):
    supported = "supported"
    mixed = "mixed"
    weak = "weak"


class EvidenceRef(BaseModel):
    """A reference to a specific piece of evidence backing a hypothesis."""
    node_id: uuid.UUID
    node_type: str
    modality: str
    label: str
    turn_index: int | None = None
    relation: str = "supports"  # supports | contradicts
    confidence: float = 0.0


class Hypothesis(BaseModel):
    """A ranked hypothesis about a psychological construct."""
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    session_id: uuid.UUID
    construct_key: str
    label: str
    score: float = Field(0.0, ge=0.0, le=1.0)
    status: HypothesisStatus = HypothesisStatus.weak
    evidence_summary: str = ""
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)
    supporting_count: int = 0
    contradicting_count: int = 0
    modalities_involved: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Construct definitions — what we look for
# ---------------------------------------------------------------------------

class _ConstructDef(BaseModel):
    """Internal definition of a psychological construct to detect."""
    key: str
    label: str
    signal_keys: list[str]
    description: str = ""


_CONSTRUCTS: list[_ConstructDef] = [
    _ConstructDef(
        key="uncertainty_anxiety",
        label="Uncertainty and anxiety",
        signal_keys=["hedging", "pause", "dysfluency", "confidence_drop", "tension", "fidgeting"],
        description="Student shows signs of uncertainty or anxiety about topics discussed",
    ),
    _ConstructDef(
        key="topic_avoidance",
        label="Topic avoidance",
        signal_keys=["avoidance", "gaze_aversion", "pause", "code_switch"],
        description="Student deflects or avoids certain topics",
    ),
    _ConstructDef(
        key="self_agency",
        label="Self-agency and autonomy",
        signal_keys=["agency"],
        description="Degree of self-direction vs. external deference in decision-making",
    ),
    _ConstructDef(
        key="external_pressure",
        label="External pressure",
        signal_keys=["agency", "avoidance", "tension"],
        description="Signs of pressure from parents, peers, or authorities",
    ),
    _ConstructDef(
        key="emotional_activation",
        label="Emotional activation",
        signal_keys=["speech_rate_fast", "speech_rate_slow", "tension", "movement",
                     "code_switch", "dysfluency"],
        description="Moments of heightened emotional engagement or distress",
    ),
    _ConstructDef(
        key="career_identity_clarity",
        label="Career identity clarity",
        signal_keys=["hedging", "agency", "avoidance", "confidence_drop"],
        description="How clear and confident the student is about career direction",
    ),
    _ConstructDef(
        key="engagement_investment",
        label="Engagement and investment",
        signal_keys=["gaze_aversion", "movement", "speech_rate_fast", "confidence_drop"],
        description="How invested the student is in the counselling process",
    ),
]


# ---------------------------------------------------------------------------
# Hypothesis generation
# ---------------------------------------------------------------------------

def generate_hypotheses(
    graph: EvidenceGraph,
    min_evidence: int = 2,
) -> list[Hypothesis]:
    """Generate and rank hypotheses from the evidence graph.

    For each construct definition, gather relevant evidence nodes,
    count supporting/contradicting edges, compute a score, and produce
    a ranked list.

    Args:
        graph: Evidence graph with nodes and edges already populated.
        min_evidence: Minimum evidence nodes to form a hypothesis.

    Returns:
        List of hypotheses sorted by score (descending).
    """
    hypotheses: list[Hypothesis] = []

    for construct in _CONSTRUCTS:
        h = _evaluate_construct(graph, construct, min_evidence)
        if h is not None:
            hypotheses.append(h)

    # Sort by score descending, then by supporting count
    hypotheses.sort(key=lambda h: (h.score, h.supporting_count), reverse=True)

    # Add hypothesis nodes to the graph and link evidence to them
    for h in hypotheses:
        h_node = graph.add_node(EvidenceNode(
            id=h.id,
            node_type=NodeType.hypothesis,
            session_id=graph.session_id,
            label=h.label,
            modality="cross_modal",
            data={"construct_key": h.construct_key, "status": h.status.value,
                  "score": h.score},
            confidence=h.score,
        ))
        for ref in h.evidence_refs:
            relation = EdgeRelation.supports if ref.relation == "supports" else EdgeRelation.contradicts
            graph.link(
                graph.get_node(ref.node_id) or h_node,  # source is the evidence
                h_node,
                relation,
                weight=ref.confidence,
                reason=f"{ref.label} → {h.label}",
            )

    logger.info(
        "Generated %d hypotheses for session %s: %s",
        len(hypotheses),
        graph.session_id,
        ", ".join(f"{h.construct_key}({h.status.value}:{h.score:.2f})" for h in hypotheses),
    )

    return hypotheses


# ---------------------------------------------------------------------------
# Internal: evaluate a single construct
# ---------------------------------------------------------------------------

def _evaluate_construct(
    graph: EvidenceGraph,
    construct: _ConstructDef,
    min_evidence: int,
) -> Hypothesis | None:
    """Evaluate a single construct against the evidence graph."""

    # Gather all evidence nodes with matching signal keys
    relevant_nodes: list[EvidenceNode] = []
    for node in graph.nodes:
        sig_key = node.data.get("signal_key", "")
        if sig_key in construct.signal_keys and node.node_type != NodeType.hypothesis:
            relevant_nodes.append(node)

    if len(relevant_nodes) < min_evidence:
        return None

    # Count cross-modal reinforcements and contradictions
    supporting = 0
    contradicting = 0
    evidence_refs: list[EvidenceRef] = []
    modalities_seen: set[str] = set()

    for node in relevant_nodes:
        modalities_seen.add(node.modality)

        # Check edges involving this node
        edges_out = graph.edges_from(node.id)
        edges_in = graph.edges_to(node.id)
        all_edges = edges_out + edges_in

        node_supports = sum(1 for e in all_edges if e.relation == EdgeRelation.supports)
        node_contradicts = sum(1 for e in all_edges if e.relation == EdgeRelation.contradicts)

        supporting += node_supports
        contradicting += node_contradicts

        # Determine this node's relation to the construct
        is_positive = _is_positive_for_construct(node, construct)
        relation = "supports" if is_positive else "contradicts"

        evidence_refs.append(EvidenceRef(
            node_id=node.id,
            node_type=node.node_type.value,
            modality=node.modality,
            label=node.label,
            turn_index=node.turn_index,
            relation=relation,
            confidence=node.confidence,
        ))

    # Score computation
    score = _compute_hypothesis_score(
        evidence_count=len(relevant_nodes),
        supporting=supporting,
        contradicting=contradicting,
        modality_count=len(modalities_seen),
        avg_confidence=sum(n.confidence for n in relevant_nodes) / len(relevant_nodes),
    )

    # Status determination
    if contradicting > supporting * 0.5 and contradicting >= 2:
        status = HypothesisStatus.mixed
    elif score >= 0.5:
        status = HypothesisStatus.supported
    else:
        status = HypothesisStatus.weak

    # Build summary
    summary = _build_evidence_summary(construct, relevant_nodes, modalities_seen, supporting, contradicting)

    return Hypothesis(
        session_id=graph.session_id,
        construct_key=construct.key,
        label=construct.label,
        score=round(score, 3),
        status=status,
        evidence_summary=summary,
        evidence_refs=evidence_refs,
        supporting_count=supporting,
        contradicting_count=contradicting,
        modalities_involved=sorted(modalities_seen),
    )


def _is_positive_for_construct(node: EvidenceNode, construct: _ConstructDef) -> bool:
    """Determine if a node is a positive or negative signal for the construct.

    E.g., high agency *contradicts* external_pressure but *supports* self_agency.
    """
    sig_key = node.data.get("signal_key", "")

    # Agency level checks
    if sig_key == "agency":
        level = node.data.get("level", "moderate")
        if construct.key == "self_agency":
            return level in ("high", "moderate")
        if construct.key == "external_pressure":
            return level == "low"  # Low agency supports external pressure hypothesis
        if construct.key == "career_identity_clarity":
            return level == "high"
        return True

    # Avoidance is always positive for avoidance-related constructs
    if sig_key == "avoidance":
        return construct.key in ("topic_avoidance", "external_pressure")

    # Everything else is a positive signal for whatever construct it's mapped to
    return True


def _compute_hypothesis_score(
    *,
    evidence_count: int,
    supporting: int,
    contradicting: int,
    modality_count: int,
    avg_confidence: float,
) -> float:
    """Compute a bounded hypothesis score in [0, 1].

    Factors:
    - Evidence volume (more evidence = more reliable, up to a cap)
    - Cross-modal support ratio
    - Number of modalities involved (multi-modal = stronger)
    - Average confidence of evidence nodes
    """
    # Volume factor: log-like curve capping around 10 pieces of evidence
    volume_factor = min(1.0, evidence_count / 8.0)

    # Support ratio: net support vs contradiction
    total_links = supporting + contradicting
    if total_links > 0:
        support_ratio = (supporting - contradicting * 0.5) / total_links
        support_ratio = max(0.0, support_ratio)
    else:
        support_ratio = 0.5  # No edges = neutral

    # Multi-modal bonus: 1 modality = 0.6, 2 = 0.85, 3 = 1.0
    modal_factor = min(1.0, 0.4 + modality_count * 0.2)

    # Weighted combination
    score = (
        0.30 * volume_factor
        + 0.25 * support_ratio
        + 0.20 * modal_factor
        + 0.25 * avg_confidence
    )

    return min(1.0, max(0.0, score))


def _build_evidence_summary(
    construct: _ConstructDef,
    nodes: list[EvidenceNode],
    modalities: set[str],
    supporting: int,
    contradicting: int,
) -> str:
    """Build a human-readable evidence summary for a hypothesis."""
    parts = [
        f"{construct.description}.",
        f"Based on {len(nodes)} evidence signals across {len(modalities)} modalities "
        f"({', '.join(sorted(modalities))}).",
    ]

    if supporting > 0:
        parts.append(f"{supporting} cross-modal reinforcements found.")
    if contradicting > 0:
        parts.append(f"{contradicting} contradicting signals noted.")

    # Highlight key evidence
    high_conf = [n for n in nodes if n.confidence >= 0.7]
    if high_conf:
        highlights = [n.label for n in high_conf[:3]]
        parts.append(f"Key signals: {'; '.join(highlights)}.")

    return " ".join(parts)
