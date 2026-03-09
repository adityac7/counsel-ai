"""Evidence graph builder — creates nodes and edges linking evidence across modalities.

An evidence graph is a lightweight directed graph where:
- **Nodes** are discrete pieces of evidence (a quote, an audio event, a video observation,
  a topic window, or a hypothesis).
- **Edges** link evidence to evidence or evidence to hypotheses, with a relationship type
  (supports, contradicts, co-occurs, context_for).

The graph is the central data structure that the correlator fills and the
hypothesis ranker reads from. It is serialized to:
  artifacts/sessions/<session_id>/analysis/evidence-graph.json
"""

from __future__ import annotations

import logging
import uuid
from enum import Enum
from typing import Any, Iterator

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

class NodeType(str, Enum):
    quote = "quote"
    audio_event = "audio_event"
    video_event = "video_event"
    topic_window = "topic_window"
    content_observation = "content_observation"
    hypothesis = "hypothesis"


class EdgeRelation(str, Enum):
    supports = "supports"
    contradicts = "contradicts"
    co_occurs = "co_occurs"
    context_for = "context_for"


class EvidenceNode(BaseModel):
    """A single piece of evidence in the graph."""
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    node_type: NodeType
    session_id: uuid.UUID
    label: str = ""
    modality: str = ""  # content / audio / video / cross_modal
    turn_index: int | None = None
    window_id: uuid.UUID | None = None
    start_ms: int | None = None
    end_ms: int | None = None
    data: dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(0.0, ge=0.0, le=1.0)


class EvidenceEdge(BaseModel):
    """A directed relationship between two evidence nodes."""
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    source_id: uuid.UUID
    target_id: uuid.UUID
    relation: EdgeRelation
    weight: float = Field(1.0, ge=0.0, le=1.0)
    reason: str = ""


class EvidenceGraph(BaseModel):
    """The full evidence graph for a session."""
    session_id: uuid.UUID
    nodes: list[EvidenceNode] = Field(default_factory=list)
    edges: list[EvidenceEdge] = Field(default_factory=list)

    # ---- fast lookups (not serialized) ----
    _node_index: dict[uuid.UUID, EvidenceNode] = {}
    _edges_from: dict[uuid.UUID, list[EvidenceEdge]] = {}
    _edges_to: dict[uuid.UUID, list[EvidenceEdge]] = {}

    def model_post_init(self, __context: Any) -> None:
        self._rebuild_indices()

    # ---- mutation helpers ----

    def add_node(self, node: EvidenceNode) -> EvidenceNode:
        self.nodes.append(node)
        self._node_index[node.id] = node
        return node

    def add_edge(self, edge: EvidenceEdge) -> EvidenceEdge:
        self.edges.append(edge)
        self._edges_from.setdefault(edge.source_id, []).append(edge)
        self._edges_to.setdefault(edge.target_id, []).append(edge)
        return edge

    def link(
        self,
        source: EvidenceNode,
        target: EvidenceNode,
        relation: EdgeRelation,
        weight: float = 1.0,
        reason: str = "",
    ) -> EvidenceEdge:
        edge = EvidenceEdge(
            source_id=source.id,
            target_id=target.id,
            relation=relation,
            weight=weight,
            reason=reason,
        )
        return self.add_edge(edge)

    # ---- query helpers ----

    def get_node(self, node_id: uuid.UUID) -> EvidenceNode | None:
        return self._node_index.get(node_id)

    def edges_from(self, node_id: uuid.UUID) -> list[EvidenceEdge]:
        return self._edges_from.get(node_id, [])

    def edges_to(self, node_id: uuid.UUID) -> list[EvidenceEdge]:
        return self._edges_to.get(node_id, [])

    def nodes_by_type(self, node_type: NodeType) -> list[EvidenceNode]:
        return [n for n in self.nodes if n.node_type == node_type]

    def nodes_in_window(self, window_id: uuid.UUID) -> list[EvidenceNode]:
        return [n for n in self.nodes if n.window_id == window_id]

    def nodes_at_turn(self, turn_index: int) -> list[EvidenceNode]:
        return [n for n in self.nodes if n.turn_index == turn_index]

    def supporting_edges(self, target_id: uuid.UUID) -> list[EvidenceEdge]:
        return [e for e in self.edges_to(target_id) if e.relation == EdgeRelation.supports]

    def contradicting_edges(self, target_id: uuid.UUID) -> list[EvidenceEdge]:
        return [e for e in self.edges_to(target_id) if e.relation == EdgeRelation.contradicts]

    def iter_cross_modal_pairs(self) -> Iterator[tuple[EvidenceNode, EvidenceNode, EvidenceEdge]]:
        """Yield (source, target, edge) for all edges linking different modalities."""
        for edge in self.edges:
            src = self._node_index.get(edge.source_id)
            tgt = self._node_index.get(edge.target_id)
            if src and tgt and src.modality != tgt.modality:
                yield src, tgt, edge

    # ---- internal ----

    def _rebuild_indices(self) -> None:
        self._node_index = {n.id: n for n in self.nodes}
        self._edges_from = {}
        self._edges_to = {}
        for e in self.edges:
            self._edges_from.setdefault(e.source_id, []).append(e)
            self._edges_to.setdefault(e.target_id, []).append(e)


# ---------------------------------------------------------------------------
# Graph builder — populates nodes from feature outputs
# ---------------------------------------------------------------------------

def build_evidence_graph(
    session_id: uuid.UUID,
    *,
    content_features: Any | None = None,
    audio_features: Any | None = None,
    video_features: Any | None = None,
    topic_windows: list[Any] | None = None,
    turns: list[Any] | None = None,
) -> EvidenceGraph:
    """Build an evidence graph from extracted features.

    This creates the *nodes* only. The correlator adds edges.
    """
    graph = EvidenceGraph(session_id=session_id)

    # 1. Topic window nodes
    for tw in (topic_windows or []):
        graph.add_node(EvidenceNode(
            id=tw.id if hasattr(tw, "id") else uuid.uuid4(),
            node_type=NodeType.topic_window,
            session_id=session_id,
            label=f"topic:{tw.topic_key}",
            modality="content",
            start_ms=tw.start_ms,
            end_ms=tw.end_ms,
            window_id=tw.id if hasattr(tw, "id") else None,
            data={"topic_key": tw.topic_key, "reliability": tw.reliability_score},
            confidence=tw.reliability_score,
        ))

    # 2. Content observation nodes
    if content_features:
        _add_content_nodes(graph, session_id, content_features)

    # 3. Audio event nodes
    if audio_features:
        _add_audio_nodes(graph, session_id, audio_features)

    # 4. Video event nodes
    if video_features:
        _add_video_nodes(graph, session_id, video_features)

    # 5. Quote nodes from turns
    for t in (turns or []):
        if getattr(t, "speaker", None) == "student" and getattr(t, "text", "").strip():
            graph.add_node(EvidenceNode(
                node_type=NodeType.quote,
                session_id=session_id,
                label=t.text[:80],
                modality="content",
                turn_index=t.turn_index,
                start_ms=t.start_ms,
                end_ms=t.end_ms,
                data={"text": t.text, "speaker": t.speaker},
                confidence=t.confidence or 0.5,
            ))

    logger.info(
        "Evidence graph for %s: %d nodes (%s)",
        session_id,
        len(graph.nodes),
        ", ".join(f"{nt.value}={len(graph.nodes_by_type(nt))}" for nt in NodeType if graph.nodes_by_type(nt)),
    )
    return graph


# ---------------------------------------------------------------------------
# Private node builders per modality
# ---------------------------------------------------------------------------

def _add_content_nodes(
    graph: EvidenceGraph,
    session_id: uuid.UUID,
    cf: Any,
) -> None:
    """Add content-derived evidence nodes (hedging, agency, avoidance, code-switch)."""
    for h in getattr(cf, "hedging_markers", []):
        graph.add_node(EvidenceNode(
            node_type=NodeType.content_observation,
            session_id=session_id,
            label=f"hedging: {h.text[:50]}",
            modality="content",
            turn_index=h.turn_index,
            start_ms=getattr(h, "start_ms", None),
            end_ms=getattr(h, "end_ms", None),
            data={"signal_key": "hedging", "text": h.text, "hedge_type": h.hedge_type},
            confidence=h.confidence,
        ))

    for a in getattr(cf, "agency_markers", []):
        graph.add_node(EvidenceNode(
            node_type=NodeType.content_observation,
            session_id=session_id,
            label=f"agency({a.level.value}): {a.text[:50]}",
            modality="content",
            turn_index=a.turn_index,
            data={"signal_key": "agency", "text": a.text, "level": a.level.value, "direction": a.direction},
            confidence=a.confidence,
        ))

    for av in getattr(cf, "avoidance_events", []):
        graph.add_node(EvidenceNode(
            node_type=NodeType.content_observation,
            session_id=session_id,
            label=f"avoidance: {av.topic_key}",
            modality="content",
            turn_index=av.turn_index,
            data={"signal_key": "avoidance", "topic_key": av.topic_key,
                  "trigger": av.trigger_text, "response": av.avoidance_text},
            confidence=av.confidence,
        ))

    for cs in getattr(cf, "code_switch_events", []):
        graph.add_node(EvidenceNode(
            node_type=NodeType.content_observation,
            session_id=session_id,
            label=f"code_switch: {cs.direction.value}",
            modality="content",
            turn_index=cs.turn_index,
            start_ms=getattr(cs, "start_ms", None),
            end_ms=getattr(cs, "end_ms", None),
            data={"signal_key": "code_switch", "direction": cs.direction.value,
                  "trigger_context": cs.trigger_context},
            confidence=cs.confidence,
        ))


def _add_audio_nodes(
    graph: EvidenceGraph,
    session_id: uuid.UUID,
    af: Any,
) -> None:
    """Add audio-derived evidence nodes (pauses, dysfluencies, turn-level anomalies)."""
    for p in getattr(af, "pauses", []):
        if p.duration_ms >= 1500:  # Only significant pauses
            graph.add_node(EvidenceNode(
                node_type=NodeType.audio_event,
                session_id=session_id,
                label=f"pause {p.duration_ms}ms",
                modality="audio",
                turn_index=p.turn_index,
                start_ms=p.start_ms,
                end_ms=p.end_ms,
                data={"signal_key": "pause", "duration_ms": p.duration_ms,
                      "is_inter_turn": p.is_inter_turn, "context": p.context},
                confidence=0.9,  # Pauses are objectively measurable
            ))

    for d in getattr(af, "dysfluencies", []):
        graph.add_node(EvidenceNode(
            node_type=NodeType.audio_event,
            session_id=session_id,
            label=f"dysfluency: {d.dysfluency_type.value}",
            modality="audio",
            turn_index=d.turn_index,
            start_ms=d.start_ms,
            end_ms=d.end_ms,
            data={"signal_key": "dysfluency", "type": d.dysfluency_type.value, "text": d.text},
            confidence=d.confidence,
        ))

    # Turn-level anomalies: confidence drops, speech rate changes
    turn_feats = getattr(af, "turn_features", [])
    if len(turn_feats) >= 3:
        avg_conf = sum(tf.confidence_score or 0.5 for tf in turn_feats) / len(turn_feats)
        avg_rate = sum(tf.speech_rate_wpm or 0 for tf in turn_feats if tf.speech_rate_wpm) or None
        rate_count = sum(1 for tf in turn_feats if tf.speech_rate_wpm)
        if avg_rate and rate_count:
            avg_rate /= rate_count

        for tf in turn_feats:
            # Vocal confidence drop
            if tf.confidence_score is not None and tf.confidence_score < avg_conf * 0.7:
                graph.add_node(EvidenceNode(
                    node_type=NodeType.audio_event,
                    session_id=session_id,
                    label=f"confidence_drop turn={tf.turn_index}",
                    modality="audio",
                    turn_index=tf.turn_index,
                    start_ms=tf.start_ms,
                    end_ms=tf.end_ms,
                    data={"signal_key": "confidence_drop",
                          "score": tf.confidence_score, "session_avg": round(avg_conf, 3)},
                    confidence=0.7,
                ))

            # Speech rate anomaly (>30% deviation)
            if avg_rate and tf.speech_rate_wpm:
                deviation = abs(tf.speech_rate_wpm - avg_rate) / avg_rate
                if deviation > 0.3:
                    direction = "fast" if tf.speech_rate_wpm > avg_rate else "slow"
                    graph.add_node(EvidenceNode(
                        node_type=NodeType.audio_event,
                        session_id=session_id,
                        label=f"speech_rate_{direction} turn={tf.turn_index}",
                        modality="audio",
                        turn_index=tf.turn_index,
                        start_ms=tf.start_ms,
                        end_ms=tf.end_ms,
                        data={"signal_key": f"speech_rate_{direction}",
                              "wpm": tf.speech_rate_wpm, "session_avg": round(avg_rate, 1),
                              "deviation_pct": round(deviation * 100, 1)},
                        confidence=0.8,
                    ))


def _add_video_nodes(
    graph: EvidenceGraph,
    session_id: uuid.UUID,
    vf: Any,
) -> None:
    """Add video-derived evidence nodes (tension, movement, gaze, engagement shifts)."""
    for te in getattr(vf, "tension_events", []):
        graph.add_node(EvidenceNode(
            node_type=NodeType.video_event,
            session_id=session_id,
            label=f"tension: {te.region} ({te.intensity:.1f})",
            modality="video",
            turn_index=te.turn_index,
            start_ms=te.timestamp_ms,
            data={"signal_key": "tension", "region": te.region,
                  "intensity": te.intensity},
            confidence=te.confidence,
        ))

    for me in getattr(vf, "movement_events", []):
        graph.add_node(EvidenceNode(
            node_type=NodeType.video_event,
            session_id=session_id,
            label=f"movement: {me.movement_type.value}",
            modality="video",
            turn_index=me.turn_index,
            start_ms=me.start_ms,
            end_ms=me.end_ms,
            data={"signal_key": "movement", "type": me.movement_type.value,
                  "magnitude": me.magnitude},
            confidence=me.confidence,
        ))

    for g in getattr(vf, "gaze_observations", []):
        if g.direction.value != "direct":  # Only non-direct gaze is interesting
            graph.add_node(EvidenceNode(
                node_type=NodeType.video_event,
                session_id=session_id,
                label=f"gaze: {g.direction.value}",
                modality="video",
                turn_index=g.turn_index,
                start_ms=g.start_ms,
                end_ms=g.end_ms,
                data={"signal_key": "gaze_aversion", "direction": g.direction.value},
                confidence=g.confidence,
            ))
