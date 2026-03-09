"""Signal normalization — scale heterogeneous features to comparable ranges.

Each signal extractor produces values in different units and ranges:
  - Speech rate: ~80–200 WPM
  - Pitch: ~75–500 Hz
  - Energy: -80 to 0 dB
  - Face visibility: 0–100%
  - Confidence scores: 0.0–1.0 (already normalized)

This module provides:
  1. Per-signal z-score normalization (relative to session baseline)
  2. Min-max scaling into [0, 1] for cross-modal comparison
  3. Deviation scoring: how far a turn/window value deviates from
     the session mean — the primary input for anomaly detection
     in the correlator.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field

import numpy as np
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Normalization profiles — expected ranges for known signal types
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SignalProfile:
    """Expected range and properties of a known signal type."""
    key: str
    unit: str
    min_val: float
    max_val: float
    higher_is: str = "neutral"  # "positive", "negative", "neutral"


# Curated profiles for cross-modal comparison
SIGNAL_PROFILES: dict[str, SignalProfile] = {
    "speech_rate_wpm": SignalProfile(
        key="speech_rate_wpm", unit="wpm", min_val=60, max_val=220,
        higher_is="neutral",
    ),
    "pitch_mean_hz": SignalProfile(
        key="pitch_mean_hz", unit="hz", min_val=75, max_val=400,
        higher_is="neutral",
    ),
    "pitch_std_hz": SignalProfile(
        key="pitch_std_hz", unit="hz", min_val=0, max_val=80,
        higher_is="neutral",
    ),
    "energy_mean_db": SignalProfile(
        key="energy_mean_db", unit="db", min_val=-60, max_val=0,
        higher_is="neutral",
    ),
    "energy_std_db": SignalProfile(
        key="energy_std_db", unit="db", min_val=0, max_val=20,
        higher_is="neutral",
    ),
    "pause_total_ms": SignalProfile(
        key="pause_total_ms", unit="ms", min_val=0, max_val=10000,
        higher_is="negative",
    ),
    "confidence_score": SignalProfile(
        key="confidence_score", unit="score", min_val=0, max_val=1,
        higher_is="positive",
    ),
    "face_visible_pct": SignalProfile(
        key="face_visible_pct", unit="pct", min_val=0, max_val=100,
        higher_is="positive",
    ),
    "tension_event_count": SignalProfile(
        key="tension_event_count", unit="count", min_val=0, max_val=10,
        higher_is="negative",
    ),
    "movement_event_count": SignalProfile(
        key="movement_event_count", unit="count", min_val=0, max_val=10,
        higher_is="neutral",
    ),
    "hedging_count": SignalProfile(
        key="hedging_count", unit="count", min_val=0, max_val=10,
        higher_is="negative",
    ),
    "avoidance_count": SignalProfile(
        key="avoidance_count", unit="count", min_val=0, max_val=5,
        higher_is="negative",
    ),
}


# ---------------------------------------------------------------------------
# Session baseline — computed from all turns
# ---------------------------------------------------------------------------


@dataclass
class SessionBaseline:
    """Per-signal statistics computed across the whole session."""
    means: dict[str, float] = field(default_factory=dict)
    stds: dict[str, float] = field(default_factory=dict)
    mins: dict[str, float] = field(default_factory=dict)
    maxs: dict[str, float] = field(default_factory=dict)
    counts: dict[str, int] = field(default_factory=dict)


def compute_baseline(turn_values: dict[str, list[float]]) -> SessionBaseline:
    """Compute session-wide statistics for each signal key.

    Args:
        turn_values: Mapping from signal key to list of per-turn values.
                     Example: {"speech_rate_wpm": [120.5, 135.2, ...]}

    Returns:
        SessionBaseline with mean, std, min, max for each key.
    """
    baseline = SessionBaseline()

    for key, values in turn_values.items():
        if not values:
            continue
        arr = np.array(values, dtype=np.float64)
        baseline.means[key] = float(np.mean(arr))
        baseline.stds[key] = float(np.std(arr)) if len(arr) > 1 else 0.0
        baseline.mins[key] = float(np.min(arr))
        baseline.maxs[key] = float(np.max(arr))
        baseline.counts[key] = len(values)

    return baseline


# ---------------------------------------------------------------------------
# Normalization functions
# ---------------------------------------------------------------------------


def z_score(value: float, mean: float, std: float) -> float:
    """Standard z-score: (value - mean) / std. Returns 0 if std is near zero."""
    if std < 1e-9:
        return 0.0
    return (value - mean) / std


def min_max_scale(value: float, min_val: float, max_val: float) -> float:
    """Scale value into [0, 1] given known min/max. Clamps to bounds."""
    if max_val - min_val < 1e-9:
        return 0.5
    scaled = (value - min_val) / (max_val - min_val)
    return max(0.0, min(1.0, scaled))


def deviation_score(value: float, mean: float, std: float) -> float:
    """Absolute deviation from mean, expressed as a 0–1 score.

    0 = at the mean, 1 = ≥3 standard deviations away.
    This is the primary anomaly signal for the correlator.
    """
    z = abs(z_score(value, mean, std))
    # Sigmoid-like mapping: 3σ → ~1.0
    return min(1.0, z / 3.0)


# ---------------------------------------------------------------------------
# Normalized turn output
# ---------------------------------------------------------------------------


class NormalizedTurnSignals(BaseModel):
    """Normalized signal values for a single turn."""
    turn_index: int

    # Raw values (for reference)
    raw: dict[str, float | None] = Field(default_factory=dict)

    # Z-scores relative to session baseline
    z_scores: dict[str, float] = Field(default_factory=dict)

    # Min-max scaled to [0, 1]
    scaled: dict[str, float] = Field(default_factory=dict)

    # Deviation from session baseline (0 = normal, 1 = highly anomalous)
    deviations: dict[str, float] = Field(default_factory=dict)

    # Composite deviation across all available signals
    composite_deviation: float = 0.0


class NormalizedSession(BaseModel):
    """All normalized signals for a session."""
    session_id: str
    baseline: dict[str, dict[str, float]] = Field(default_factory=dict)
    turns: list[NormalizedTurnSignals] = Field(default_factory=list)
    anomalous_turns: list[int] = Field(
        default_factory=list,
        description="Turn indices where composite_deviation > 0.5",
    )


# ---------------------------------------------------------------------------
# Main normalization pipeline
# ---------------------------------------------------------------------------


def _extract_turn_values(aligned_turns: list) -> tuple[dict[str, list[float]], dict[int, dict[str, float | None]]]:
    """Pull raw numeric values from aligned turns into per-signal lists.

    Returns:
        (turn_values, per_turn_raw)
        - turn_values: signal_key → [values across turns]
        - per_turn_raw: turn_index → {signal_key: value}
    """
    turn_values: dict[str, list[float]] = {}
    per_turn_raw: dict[int, dict[str, float | None]] = {}

    for at in aligned_turns:
        ti = at.turn_index
        raw: dict[str, float | None] = {}

        # Audio signals
        if at.audio:
            a = at.audio
            for key, val in [
                ("speech_rate_wpm", a.speech_rate_wpm),
                ("pitch_mean_hz", a.pitch_mean_hz),
                ("pitch_std_hz", a.pitch_std_hz),
                ("energy_mean_db", a.energy_mean_db),
                ("energy_std_db", a.energy_std_db),
                ("pause_total_ms", float(a.pause_total_ms) if a.pause_total_ms else None),
                ("confidence_score", a.confidence_score),
            ]:
                raw[key] = val
                if val is not None:
                    turn_values.setdefault(key, []).append(val)

        # Video signals
        if at.video:
            v = at.video
            for key, val in [
                ("face_visible_pct", v.face_visible_pct),
                ("tension_event_count", float(v.tension_event_count)),
                ("movement_event_count", float(v.movement_event_count)),
            ]:
                raw[key] = val
                if val is not None:
                    turn_values.setdefault(key, []).append(val)

        # Content counts
        hedging_n = len(at.hedging_markers)
        avoidance_n = len(at.avoidance_events)
        raw["hedging_count"] = float(hedging_n)
        raw["avoidance_count"] = float(avoidance_n)
        if hedging_n > 0:
            turn_values.setdefault("hedging_count", []).append(float(hedging_n))
        if avoidance_n > 0:
            turn_values.setdefault("avoidance_count", []).append(float(avoidance_n))

        per_turn_raw[ti] = raw

    return turn_values, per_turn_raw


def normalize_session(
    session_id: str,
    aligned_turns: list,
) -> NormalizedSession:
    """Normalize all signal values for a session.

    Args:
        session_id: Session UUID string.
        aligned_turns: List of AlignedTurn objects from timeline alignment.

    Returns:
        NormalizedSession with z-scores, scaled values, and deviation scores.
    """
    if not aligned_turns:
        return NormalizedSession(session_id=session_id)

    # Extract raw values
    turn_values, per_turn_raw = _extract_turn_values(aligned_turns)

    # Compute baseline
    baseline = compute_baseline(turn_values)

    # Normalize each turn
    normalized_turns: list[NormalizedTurnSignals] = []
    anomalous_indices: list[int] = []

    for at in aligned_turns:
        ti = at.turn_index
        raw = per_turn_raw.get(ti, {})

        z_scores: dict[str, float] = {}
        scaled: dict[str, float] = {}
        deviations: dict[str, float] = {}

        for key, val in raw.items():
            if val is None:
                continue

            # Z-score (session-relative)
            if key in baseline.means and key in baseline.stds:
                z = z_score(val, baseline.means[key], baseline.stds[key])
                z_scores[key] = round(z, 3)
                deviations[key] = round(deviation_score(val, baseline.means[key], baseline.stds[key]), 3)

            # Min-max scale (use profile if available, else session range)
            profile = SIGNAL_PROFILES.get(key)
            if profile:
                scaled[key] = round(min_max_scale(val, profile.min_val, profile.max_val), 3)
            elif key in baseline.mins and key in baseline.maxs:
                scaled[key] = round(min_max_scale(val, baseline.mins[key], baseline.maxs[key]), 3)

        # Composite deviation: RMS of individual deviations
        if deviations:
            dev_vals = list(deviations.values())
            composite = math.sqrt(sum(d * d for d in dev_vals) / len(dev_vals))
        else:
            composite = 0.0

        nt = NormalizedTurnSignals(
            turn_index=ti,
            raw={k: v for k, v in raw.items() if v is not None},
            z_scores=z_scores,
            scaled=scaled,
            deviations=deviations,
            composite_deviation=round(composite, 3),
        )
        normalized_turns.append(nt)

        if composite > 0.5:
            anomalous_indices.append(ti)

    # Serialize baseline for output
    baseline_dict: dict[str, dict[str, float]] = {}
    for key in baseline.means:
        baseline_dict[key] = {
            "mean": round(baseline.means[key], 3),
            "std": round(baseline.stds.get(key, 0), 3),
            "min": round(baseline.mins.get(key, 0), 3),
            "max": round(baseline.maxs.get(key, 0), 3),
            "count": baseline.counts.get(key, 0),
        }

    logger.info(
        "Normalized %d turns for session %s: %d signals tracked, %d anomalous turns",
        len(normalized_turns),
        session_id,
        len(baseline.means),
        len(anomalous_indices),
    )

    return NormalizedSession(
        session_id=session_id,
        baseline=baseline_dict,
        turns=normalized_turns,
        anomalous_turns=anomalous_indices,
    )
