"""Common signal processing — timeline alignment, normalization, reliability scoring."""

from counselai.signals.common.normalization import (
    NormalizedSession,
    NormalizedTurnSignals,
    SessionBaseline,
    compute_baseline,
    deviation_score,
    min_max_scale,
    normalize_session,
    z_score,
)
from counselai.signals.common.reliability import (
    adjust_observation_confidence,
    score_session_reliability,
)
from counselai.signals.common.schemas import (
    Modality,
    ModalityReliability,
    ObservationSource,
    SessionReliability,
    SignalObservation,
    TimeSpan,
    TopicWindow,
)
from counselai.signals.common.timeline import (
    AlignedSession,
    AlignedTurn,
    AlignedWindow,
    align_session_signals,
)

__all__ = [
    # Timeline
    "AlignedSession",
    "AlignedTurn",
    "AlignedWindow",
    "align_session_signals",
    # Normalization
    "NormalizedSession",
    "NormalizedTurnSignals",
    "SessionBaseline",
    "compute_baseline",
    "deviation_score",
    "min_max_scale",
    "normalize_session",
    "z_score",
    # Reliability
    "adjust_observation_confidence",
    "score_session_reliability",
    # Schemas
    "Modality",
    "ModalityReliability",
    "ObservationSource",
    "SessionReliability",
    "SignalObservation",
    "TimeSpan",
    "TopicWindow",
]
