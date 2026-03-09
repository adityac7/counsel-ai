"""Async job entrypoints for post-session processing.

Each job function is a standalone entrypoint that can be called
by Dramatiq workers or invoked directly for testing.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid

from counselai.ingest.artifact_store import ArtifactStore
from counselai.signals.content.extractor import CanonicalTurn, ContentSignalExtractor
from counselai.signals.content.schemas import ContentFeatures
from counselai.analysis.topic_windows import (
    build_topic_windows,
    windows_to_observations,
)
from counselai.signals.common.schemas import TopicWindow

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _load_turns_raw(session_id: str, store: ArtifactStore | None = None) -> list[dict]:
    """Load canonical turns.jsonl as raw dicts."""
    store = store or ArtifactStore()
    turns_path = store.session_dir(session_id) / "turns.jsonl"
    if not turns_path.exists():
        logger.warning("turns.jsonl not found for session %s", session_id)
        return []
    turns = []
    for line in turns_path.read_text().splitlines():
        line = line.strip()
        if line:
            turns.append(json.loads(line))
    return turns


def _load_canonical_turns(session_id: str, store: ArtifactStore | None = None) -> list[CanonicalTurn]:
    """Load canonical turns from turns.jsonl as CanonicalTurn objects."""
    raw = _load_turns_raw(session_id, store)
    return [
        CanonicalTurn(
            turn_index=t["turn_index"],
            speaker=t["speaker"],
            text=t["text"],
            start_ms=t.get("start_ms", 0),
            end_ms=t.get("end_ms", 0),
            confidence=t.get("confidence"),
        )
        for t in raw
    ]


# ---------------------------------------------------------------------------
# Content extraction job
# ---------------------------------------------------------------------------

async def _run_content_extraction_async(
    session_id: str,
    store: ArtifactStore,
) -> tuple[ContentFeatures, list[TopicWindow]]:
    """Async core of content extraction."""
    from counselai.live.providers.gemini import GeminiSynthesisProvider

    uid = uuid.UUID(session_id)
    turns = _load_canonical_turns(session_id, store)

    if not turns:
        logger.error("No turns found — aborting content extraction for %s", session_id)
        empty = ContentFeatures(session_id=uid, reliability_score=0.0)
        return empty, []

    # Run content signal extractor (deterministic + LLM)
    synthesis = GeminiSynthesisProvider()
    extractor = ContentSignalExtractor(synthesis)
    features = await extractor.extract(uid, turns)

    logger.info(
        "Content extraction for %s: %d topics, %d avoidance, "
        "%d hedging, %d agency, %d code-switch, reliability=%.3f",
        session_id,
        len(features.topics),
        len(features.avoidance_events),
        len(features.hedging_markers),
        len(features.agency_markers),
        len(features.code_switch_events),
        features.reliability_score,
    )

    # Build topic windows
    windows = build_topic_windows(uid, features, turns)
    logger.info("Built %d topic windows for session %s", len(windows), session_id)

    # Convert to observations (for later DB persistence)
    observations = windows_to_observations(windows, features)
    logger.info("Generated %d signal observations for session %s", len(observations), session_id)

    # Persist artifacts
    session_dir = store.session_dir(session_id)
    features_dir = session_dir / "features"
    features_dir.mkdir(parents=True, exist_ok=True)

    (features_dir / "content.json").write_text(
        features.model_dump_json(indent=2), encoding="utf-8",
    )
    (features_dir / "topic_windows.json").write_text(
        json.dumps([w.model_dump(mode="json") for w in windows], indent=2, default=str),
        encoding="utf-8",
    )
    (features_dir / "content_observations.json").write_text(
        json.dumps(observations, indent=2, default=str), encoding="utf-8",
    )

    return features, windows


def run_content_extraction(session_id: str) -> dict:
    """Synchronous entry point for content signal extraction.

    Loads turns, runs deterministic + Gemini LLM extraction, builds
    topic windows, writes features/content.json, topic_windows.json,
    and content_observations.json.

    Returns content features as a dict.
    """
    store = ArtifactStore()
    sid = str(session_id)

    loop = asyncio.new_event_loop()
    try:
        features, windows = loop.run_until_complete(
            _run_content_extraction_async(sid, store)
        )
    finally:
        loop.close()

    result = features.model_dump(mode="json")
    logger.info(
        "Content features written for session %s (reliability=%.2f, topics=%d)",
        sid,
        features.reliability_score,
        len(features.topics),
    )
    return result


# ---------------------------------------------------------------------------
# Video extraction job
# ---------------------------------------------------------------------------

def run_video_extraction(
    session_id: str,
    video_path: str | None = None,
    use_gemini: bool = True,
) -> dict:
    """Run video signal extraction for a session.

    Args:
        session_id: UUID of the session to process.
        video_path: Explicit path to video file (optional).
        use_gemini: Whether to use Gemini multimodal analysis.

    Returns:
        Summary dict with key metrics.
    """
    from counselai.signals.video.extractor import extract_video_signals

    store = ArtifactStore()

    # Load turns if available
    turns = store.read_jsonl(session_id, "turns.jsonl")

    # Load topic windows if available
    topic_windows_data = store.read_json(session_id, "analysis/topic_windows.json")
    topic_windows = topic_windows_data if isinstance(topic_windows_data, list) else []

    logger.info("Starting video extraction for session %s", session_id)

    features = extract_video_signals(
        session_id=session_id,
        video_path=video_path,
        turns=turns,
        topic_windows=topic_windows,
        use_gemini=use_gemini,
        artifact_store=store,
    )

    summary = {
        "session_id": session_id,
        "frame_count": features.frame_count or 0,
        "face_visible_pct": features.total_face_visible_pct,
        "reliability_score": features.reliability_score,
        "turn_features_count": len(features.turn_features),
        "gaze_observations_count": len(features.gaze_observations),
        "tension_events_count": len(features.tension_events),
        "movement_events_count": len(features.movement_events),
    }

    logger.info("Video extraction complete: %s", summary)
    return summary


# ---------------------------------------------------------------------------
# Profile synthesis job
# ---------------------------------------------------------------------------

async def _run_profile_synthesis_async(session_id: str) -> dict:
    """Async core of profile synthesis."""
    from counselai.profiles.synthesizer import synthesize_session_profile

    response = await synthesize_session_profile(session_id)
    profile = response.parsed_profile

    result: dict = {
        "session_id": session_id,
        "is_valid": response.is_valid,
        "validation_errors": response.validation_errors,
    }

    if profile:
        result.update({
            "profile_version": profile.profile_version,
            "constructs_count": len(profile.counsellor_view.constructs),
            "red_flags_count": len(profile.red_flags),
            "student_strengths_count": len(profile.student_view.strengths),
            "school_topics_count": len(profile.school_view.primary_topics),
        })

    return result


def run_profile_synthesis(session_id: str) -> dict:
    """Synchronous entry point for profile synthesis.

    Loads all evidence artifacts, runs three-step LLM synthesis
    (counsellor → student → school views), validates outputs,
    and writes analysis/profile.json.

    Returns summary dict.
    """
    import asyncio

    loop = asyncio.new_event_loop()
    try:
        result = loop.run_until_complete(
            _run_profile_synthesis_async(str(session_id))
        )
    finally:
        loop.close()

    logger.info("Profile synthesis result for session %s: %s", session_id, result)
    return result


# ---------------------------------------------------------------------------
# Evidence correlation job
# ---------------------------------------------------------------------------

def run_evidence_correlation(session_id: str) -> dict:
    """Build the evidence graph, run cross-modal correlation, and generate hypotheses.

    Loads content, audio, and video features from artifact JSON files,
    builds an evidence graph with nodes, runs the correlator to add
    edges (reinforcements, contradictions, co-occurrences), generates
    ranked hypotheses, and persists everything.

    Returns:
        Summary dict with graph and hypothesis stats.
    """
    from counselai.analysis.evidence_graph import build_evidence_graph
    from counselai.analysis.correlator import correlate
    from counselai.analysis.hypotheses import generate_hypotheses
    from counselai.signals.content.schemas import ContentFeatures
    from counselai.signals.audio.schemas import AudioFeatures
    from counselai.signals.video.schemas import VideoFeatures
    from counselai.signals.common.schemas import TopicWindow

    store = ArtifactStore()
    sid = str(session_id)
    uid = uuid.UUID(sid)

    # Load features from artifact files
    content_features = _load_features(store, sid, "features/content.json", ContentFeatures)
    audio_features = _load_features(store, sid, "features/audio.json", AudioFeatures)
    video_features = _load_features(store, sid, "features/video.json", VideoFeatures)

    # Load topic windows
    topic_windows_raw = store.read_json(sid, "features/topic_windows.json")
    topic_windows = []
    if isinstance(topic_windows_raw, list):
        for tw in topic_windows_raw:
            try:
                topic_windows.append(TopicWindow(**tw))
            except Exception:
                logger.warning("Skipping invalid topic window: %s", tw)

    # Load canonical turns
    turns = _load_canonical_turns(sid, store)

    logger.info(
        "Building evidence graph for %s (content=%s, audio=%s, video=%s, "
        "windows=%d, turns=%d)",
        sid,
        "yes" if content_features else "no",
        "yes" if audio_features else "no",
        "yes" if video_features else "no",
        len(topic_windows),
        len(turns),
    )

    # Build graph nodes
    graph = build_evidence_graph(
        uid,
        content_features=content_features,
        audio_features=audio_features,
        video_features=video_features,
        topic_windows=topic_windows,
        turns=turns,
    )

    # Run cross-modal correlation (adds edges)
    graph = correlate(graph)

    # Generate and rank hypotheses (adds hypothesis nodes + edges)
    hypotheses = generate_hypotheses(graph)

    # Persist artifacts
    session_dir = store.session_dir(sid)
    analysis_dir = session_dir / "analysis"
    analysis_dir.mkdir(parents=True, exist_ok=True)

    # Evidence graph JSON
    (analysis_dir / "evidence-graph.json").write_text(
        graph.model_dump_json(indent=2), encoding="utf-8",
    )

    # Hypotheses JSON (separate file for easy access)
    (analysis_dir / "hypotheses.json").write_text(
        json.dumps(
            [h.model_dump(mode="json") for h in hypotheses],
            indent=2, default=str,
        ),
        encoding="utf-8",
    )

    # Cross-modal observations for DB persistence
    cross_modal_obs = _graph_to_cross_modal_observations(graph, uid)
    (analysis_dir / "cross_modal_observations.json").write_text(
        json.dumps(cross_modal_obs, indent=2, default=str),
        encoding="utf-8",
    )

    summary = {
        "session_id": sid,
        "node_count": len(graph.nodes),
        "edge_count": len(graph.edges),
        "hypothesis_count": len(hypotheses),
        "hypotheses": [
            {"construct": h.construct_key, "status": h.status.value,
             "score": h.score, "modalities": h.modalities_involved}
            for h in hypotheses
        ],
        "cross_modal_observations": len(cross_modal_obs),
    }

    logger.info("Evidence correlation complete for %s: %s", sid, summary)
    return summary


def _load_features(
    store: ArtifactStore,
    session_id: str,
    rel_path: str,
    model_class: type,
) -> object | None:
    """Load a features JSON file and parse it into a Pydantic model."""
    data = store.read_json(session_id, rel_path)
    if data is None:
        return None
    try:
        return model_class(**data)
    except Exception as e:
        logger.warning("Failed to parse %s for session %s: %s", rel_path, session_id, e)
        return None


def _graph_to_cross_modal_observations(
    graph: "EvidenceGraph",
    session_id: uuid.UUID,
) -> list[dict]:
    """Extract cross-modal signal observations from graph edges for DB persistence."""
    from counselai.signals.common.schemas import Modality, ObservationSource

    observations = []
    seen_pairs: set[tuple] = set()

    for src, tgt, edge in graph.iter_cross_modal_pairs():
        pair_key = (src.id, tgt.id) if src.id < tgt.id else (tgt.id, src.id)
        if pair_key in seen_pairs:
            continue
        seen_pairs.add(pair_key)

        if edge.relation.value not in ("supports", "contradicts"):
            continue

        observations.append({
            "session_id": str(session_id),
            "window_id": str(src.window_id or tgt.window_id) if (src.window_id or tgt.window_id) else None,
            "turn_index": src.turn_index or tgt.turn_index,
            "modality": Modality.cross_modal.value,
            "signal_key": f"cross_modal_{edge.relation.value}",
            "value_json": {
                "source_modality": src.modality,
                "target_modality": tgt.modality,
                "source_signal": src.data.get("signal_key", ""),
                "target_signal": tgt.data.get("signal_key", ""),
                "source_label": src.label,
                "target_label": tgt.label,
            },
            "confidence": edge.weight,
            "source": ObservationSource.model_inferred.value,
            "evidence_ref_json": {
                "source_node_id": str(src.id),
                "target_node_id": str(tgt.id),
                "edge_id": str(edge.id),
                "reason": edge.reason,
            },
        })

    return observations


# ---------------------------------------------------------------------------
# Audio extraction job
# ---------------------------------------------------------------------------

def run_audio_extraction(
    session_id: str,
    audio_path: str | None = None,
    use_gemini: bool = True,
) -> dict:
    """Run audio signal extraction for a session.

    Args:
        session_id: UUID of the session.
        audio_path: Explicit path (optional; auto-resolved from artifact store).
        use_gemini: Whether to use Gemini dysfluency enrichment.

    Returns:
        Summary dict.
    """
    from counselai.signals.audio.extractor import extract_audio_features

    store = ArtifactStore()
    sid = str(session_id)

    # Resolve audio path
    if audio_path is None:
        for candidate in ["audio.wav", "audio.raw.webm"]:
            p = store.session_dir(sid) / candidate
            if p.exists():
                audio_path = str(p)
                break
    if audio_path is None:
        logger.error("No audio file found for session %s", sid)
        return {"session_id": sid, "error": "no audio file"}

    turns = _load_turns_raw(sid, store)

    # Load topic windows if available
    features_dir = store.features_dir(sid)
    tw_path = features_dir / "topic_windows.json"
    windows = None
    if tw_path.exists():
        windows = json.loads(tw_path.read_text())

    loop = asyncio.new_event_loop()
    try:
        features = loop.run_until_complete(
            extract_audio_features(
                uuid.UUID(sid), audio_path, turns, windows, use_gemini=use_gemini,
            )
        )
    finally:
        loop.close()

    # Persist
    (features_dir / "audio.json").write_text(
        features.model_dump_json(indent=2), encoding="utf-8",
    )

    summary = {
        "session_id": sid,
        "turn_features_count": len(features.turn_features),
        "pause_count": len(features.pauses),
        "dysfluency_count": len(features.dysfluencies),
        "reliability_score": features.reliability_score,
    }
    logger.info("Audio extraction complete: %s", summary)
    return summary


# ---------------------------------------------------------------------------
# Timeline alignment, normalization & reliability scoring job
# ---------------------------------------------------------------------------

def run_timeline_alignment(session_id: str) -> dict:
    """Run cross-modal timeline alignment, normalization, and reliability scoring.

    Loads content, audio, and video features produced by Tasks 6-8, then:
      1. Aligns all signals on the shared turn/topic-window timeline.
      2. Normalizes signal values (z-score, min-max, deviation scoring).
      3. Scores per-modality and overall reliability.
      4. Adjusts observation confidence by source reliability.
      5. Persists aligned output to the analysis/ artifact directory.

    Returns:
        Summary dict with key metrics.
    """
    from counselai.signals.common.timeline import align_session_signals
    from counselai.signals.common.normalization import normalize_session
    from counselai.signals.common.reliability import (
        adjust_observation_confidence,
        score_session_reliability,
    )
    from counselai.signals.content.schemas import ContentFeatures
    from counselai.signals.audio.schemas import AudioFeatures
    from counselai.signals.video.schemas import VideoFeatures

    store = ArtifactStore()
    sid = str(session_id)
    uid = uuid.UUID(sid)

    # -- Load turns --------------------------------------------------------
    turns_raw = _load_turns_raw(sid, store)
    if not turns_raw:
        logger.error("No turns found — cannot align session %s", sid)
        return {"session_id": sid, "error": "no turns"}

    # -- Load feature outputs from each extractor --------------------------
    features_dir = store.features_dir(sid)

    content: ContentFeatures | None = None
    content_path = features_dir / "content.json"
    if content_path.exists():
        content = ContentFeatures.model_validate_json(content_path.read_text())
        logger.info("Loaded content features for %s", sid)

    audio: AudioFeatures | None = None
    audio_path = features_dir / "audio.json"
    if audio_path.exists():
        audio = AudioFeatures.model_validate_json(audio_path.read_text())
        logger.info("Loaded audio features for %s", sid)

    video: VideoFeatures | None = None
    video_path = features_dir / "video.json"
    if video_path.exists():
        video = VideoFeatures.model_validate_json(video_path.read_text())
        logger.info("Loaded video features for %s", sid)

    # -- Load topic windows ------------------------------------------------
    from counselai.signals.common.schemas import TopicWindow

    tw_path = features_dir / "topic_windows.json"
    topic_windows: list[TopicWindow] = []
    if tw_path.exists():
        raw_windows = json.loads(tw_path.read_text())
        topic_windows = [TopicWindow.model_validate(w) for w in raw_windows]

    # -- Step 1: Timeline alignment ----------------------------------------
    aligned = align_session_signals(
        session_id=uid,
        turns_raw=turns_raw,
        topic_windows=topic_windows,
        content=content,
        audio=audio,
        video=video,
    )

    # -- Step 2: Normalization ---------------------------------------------
    normalized = normalize_session(sid, aligned.turns)

    # -- Step 3: Reliability scoring ---------------------------------------
    reliability = score_session_reliability(
        session_id=uid,
        content=content,
        audio=audio,
        video=video,
        session_duration_ms=aligned.duration_ms,
    )

    # -- Step 4: Adjust observation confidence by reliability --------------
    reliability_map = {m.modality: m.score for m in reliability.modalities}
    adjusted_observations = adjust_observation_confidence(
        aligned.observations, reliability_map,
    )

    # -- Step 5: Persist ---------------------------------------------------
    analysis_dir = store.analysis_dir(sid)

    # Aligned session (turns + windows + observations)
    (analysis_dir / "aligned_session.json").write_text(
        aligned.model_dump_json(indent=2), encoding="utf-8",
    )

    # Normalized signals
    (analysis_dir / "normalized_signals.json").write_text(
        normalized.model_dump_json(indent=2), encoding="utf-8",
    )

    # Reliability report
    (analysis_dir / "reliability.json").write_text(
        reliability.model_dump_json(indent=2), encoding="utf-8",
    )

    # Adjusted observations (primary input for evidence graph)
    (analysis_dir / "observations.json").write_text(
        json.dumps(
            [o.model_dump(mode="json") for o in adjusted_observations],
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )

    from counselai.signals.common.schemas import Modality as _Mod

    summary = {
        "session_id": sid,
        "aligned_turns": len(aligned.turns),
        "aligned_windows": len(aligned.windows),
        "observations": len(adjusted_observations),
        "anomalous_turns": len(normalized.anomalous_turns),
        "reliability_overall": reliability.overall_score,
        "reliability_content": reliability_map.get(_Mod.content, 0.0),
        "reliability_audio": reliability_map.get(_Mod.audio, 0.0),
        "reliability_video": reliability_map.get(_Mod.video, 0.0),
        "modalities_available": [m.value for m in aligned.modalities_available],
    }

    logger.info("Timeline alignment complete for session %s: %s", sid, summary)
    return summary
