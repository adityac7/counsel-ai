"""Cross-modal reliability scoring — assesses evidence quality per modality and overall.

Each extractor already computes its own reliability score (audio quality,
video face visibility, content transcript confidence). This module:

  1. Collects per-modality reliability from each extractor's output.
  2. Applies cross-modal consistency checks (do modalities agree?).
  3. Computes a coverage-weighted overall reliability score.
  4. Annotates every SignalObservation with an adjusted confidence
     that accounts for the source modality's reliability.

The output ``SessionReliability`` is used by the evidence graph and
hypothesis ranker to weight evidence appropriately.
"""

from __future__ import annotations

import logging
import uuid
from typing import Sequence

from counselai.signals.audio.schemas import AudioFeatures
from counselai.signals.common.schemas import (
    Modality,
    ModalityReliability,
    SessionReliability,
    SignalObservation,
)
from counselai.signals.content.schemas import ContentFeatures
from counselai.signals.video.schemas import VideoFeatures

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Per-modality reliability extraction
# ---------------------------------------------------------------------------


def _content_reliability(
    features: ContentFeatures | None,
    session_duration_ms: int,
) -> ModalityReliability:
    """Assess content extraction reliability."""
    if features is None:
        return ModalityReliability(
            modality=Modality.content,
            score=0.0,
            reason="Content features not available",
            sample_count=0,
            coverage_pct=0.0,
        )

    topic_count = len(features.topics)
    hedging_count = len(features.hedging_markers)
    sample_count = topic_count + hedging_count + len(features.agency_markers)

    # Coverage: estimate from turn indices covered by topics
    covered_turns: set[int] = set()
    for topic in features.topics:
        covered_turns.update(topic.turn_indices)

    # Simple quality checks
    reasons: list[str] = []
    score = features.reliability_score

    if topic_count == 0:
        score = min(score, 0.3)
        reasons.append("no topics extracted")
    if features.dominant_language is None:
        score = min(score, 0.5)
        reasons.append("language not detected")

    return ModalityReliability(
        modality=Modality.content,
        score=round(score, 3),
        reason="; ".join(reasons) if reasons else "OK",
        sample_count=sample_count,
        coverage_pct=min(100.0, len(covered_turns) * 10),  # rough estimate
    )


def _audio_reliability(
    features: AudioFeatures | None,
    session_duration_ms: int,
) -> ModalityReliability:
    """Assess audio signal reliability."""
    if features is None:
        return ModalityReliability(
            modality=Modality.audio,
            score=0.0,
            reason="Audio features not available",
            sample_count=0,
            coverage_pct=0.0,
        )

    turn_count = len(features.turn_features)
    reasons: list[str] = []
    score = features.reliability_score

    # Check pitch extraction coverage
    pitched = sum(1 for t in features.turn_features if t.pitch_mean_hz is not None)
    if turn_count > 0:
        pitch_coverage = pitched / turn_count
        if pitch_coverage < 0.3:
            score = min(score, 0.5)
            reasons.append(f"pitch extracted in only {pitched}/{turn_count} turns")
    else:
        score = min(score, 0.2)
        reasons.append("no turn-level features")

    # Check timeline coverage
    if session_duration_ms > 0 and features.turn_features:
        covered_ms = sum(
            max(0, t.end_ms - t.start_ms) for t in features.turn_features
        )
        coverage_pct = min(100.0, (covered_ms / session_duration_ms) * 100)
    else:
        coverage_pct = 0.0

    return ModalityReliability(
        modality=Modality.audio,
        score=round(score, 3),
        reason="; ".join(reasons) if reasons else "OK",
        sample_count=turn_count,
        coverage_pct=round(coverage_pct, 1),
    )


def _video_reliability(
    features: VideoFeatures | None,
    session_duration_ms: int,
) -> ModalityReliability:
    """Assess video signal reliability."""
    if features is None:
        return ModalityReliability(
            modality=Modality.video,
            score=0.0,
            reason="Video features not available",
            sample_count=0,
            coverage_pct=0.0,
        )

    reasons: list[str] = []
    score = features.reliability_score
    turn_count = len(features.turn_features)

    # Face visibility is the primary quality indicator for video
    if features.total_face_visible_pct < 30:
        score = min(score, 0.4)
        reasons.append(f"face visible only {features.total_face_visible_pct:.0f}% of time")

    if features.frame_count is not None and features.frame_count < 10:
        score = min(score, 0.3)
        reasons.append(f"only {features.frame_count} frames extracted")

    # Timeline coverage
    coverage_pct = 0.0
    if session_duration_ms > 0 and features.video_duration_ms:
        coverage_pct = min(100.0, (features.video_duration_ms / session_duration_ms) * 100)

    return ModalityReliability(
        modality=Modality.video,
        score=round(score, 3),
        reason="; ".join(reasons) if reasons else "OK",
        sample_count=turn_count,
        coverage_pct=round(coverage_pct, 1),
    )


# ---------------------------------------------------------------------------
# Cross-modal consistency bonus/penalty
# ---------------------------------------------------------------------------


def _cross_modal_adjustment(
    modalities: list[ModalityReliability],
) -> float:
    """Compute a small adjustment based on how many modalities are available.

    More modalities = more cross-validation potential = higher confidence.
    """
    available = [m for m in modalities if m.score > 0.1]
    count = len(available)

    if count >= 3:
        return 0.05  # Triple-modal — slight bonus
    elif count == 2:
        return 0.0  # Dual-modal — neutral
    elif count == 1:
        return -0.05  # Single-modal — slight penalty (no cross-validation)
    else:
        return -0.1  # No modalities — big penalty


# ---------------------------------------------------------------------------
# Observation confidence adjustment
# ---------------------------------------------------------------------------


def adjust_observation_confidence(
    observations: Sequence[SignalObservation],
    reliability_map: dict[Modality, float],
) -> list[SignalObservation]:
    """Adjust observation confidence by its source modality's reliability.

    The adjusted confidence is: original_confidence × modality_reliability.
    This ensures that observations from unreliable modalities are
    down-weighted in the evidence graph.

    Returns new observation objects (does not mutate originals).
    """
    adjusted: list[SignalObservation] = []

    for obs in observations:
        modality_reliability = reliability_map.get(obs.modality, 0.5)
        new_confidence = round(obs.confidence * modality_reliability, 3)

        adjusted.append(obs.model_copy(update={"confidence": new_confidence}))

    return adjusted


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def score_session_reliability(
    session_id: uuid.UUID,
    content: ContentFeatures | None = None,
    audio: AudioFeatures | None = None,
    video: VideoFeatures | None = None,
    session_duration_ms: int = 0,
) -> SessionReliability:
    """Compute comprehensive reliability scores for a session.

    This is the primary entry point. Returns a SessionReliability with
    per-modality breakdowns and a weighted overall score.

    Args:
        session_id: Session UUID.
        content: Content features (or None).
        audio: Audio features (or None).
        video: Video features (or None).
        session_duration_ms: Total session duration for coverage calculations.

    Returns:
        SessionReliability with per-modality and overall scores.
    """
    modalities = [
        _content_reliability(content, session_duration_ms),
        _audio_reliability(audio, session_duration_ms),
        _video_reliability(video, session_duration_ms),
    ]

    # Weighted overall: weight by coverage, but floor at equal weights if
    # all coverages are zero (fallback to simple average)
    total_coverage = sum(m.coverage_pct for m in modalities)
    notes: list[str] = []

    if total_coverage > 0:
        overall = sum(
            m.score * (m.coverage_pct / total_coverage)
            for m in modalities
        )
    else:
        # Fallback: average of non-zero scores
        non_zero = [m.score for m in modalities if m.score > 0]
        overall = sum(non_zero) / len(non_zero) if non_zero else 0.0
        notes.append("no coverage data available; used simple average")

    # Cross-modal adjustment
    adjustment = _cross_modal_adjustment(modalities)
    overall = max(0.0, min(1.0, overall + adjustment))
    if adjustment != 0:
        notes.append(
            f"cross-modal adjustment: {adjustment:+.2f} "
            f"({sum(1 for m in modalities if m.score > 0.1)} modalities available)"
        )

    # Session-level notes
    unavailable = [m for m in modalities if m.score == 0.0]
    for m in unavailable:
        notes.append(f"{m.modality.value} modality unavailable")

    low_quality = [m for m in modalities if 0 < m.score < 0.4]
    for m in low_quality:
        notes.append(f"{m.modality.value} quality is low ({m.score:.2f}): {m.reason}")

    result = SessionReliability(
        session_id=session_id,
        modalities=modalities,
        overall_score=round(overall, 3),
        notes=notes,
    )

    logger.info(
        "Session %s reliability: overall=%.3f, content=%.2f, audio=%.2f, video=%.2f",
        session_id,
        result.overall_score,
        modalities[0].score,
        modalities[1].score,
        modalities[2].score,
    )

    return result
