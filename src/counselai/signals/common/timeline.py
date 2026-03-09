"""Timeline alignment — joins content, audio, and video signals on turns and topic windows.

This module is the backbone of cross-modal analysis. It takes the
independent outputs of the three signal extractors and aligns them
onto a shared timeline indexed by:
  1. Turn index (finest grain)
  2. Topic window (semantic grain)
  3. Session-wide (coarsest grain)

The output is a list of ``AlignedTurn`` and ``AlignedWindow`` objects
that downstream modules (evidence graph, correlator, hypotheses) consume.
"""

from __future__ import annotations

import logging
import uuid
from typing import Sequence

from pydantic import BaseModel, Field

from counselai.signals.audio.schemas import (
    AudioFeatures,
    TurnAudioFeatures,
    WindowAudioSummary,
)
from counselai.signals.common.schemas import (
    Modality,
    ObservationSource,
    SignalObservation,
    TopicWindow,
)
from counselai.signals.content.schemas import (
    AgencyMarker,
    AvoidanceEvent,
    CodeSwitchEvent,
    ContentFeatures,
    HedgingMarker,
)
from counselai.signals.video.schemas import (
    GazeDirection,
    TurnVideoFeatures,
    VideoFeatures,
    WindowVideoSummary,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Aligned output models
# ---------------------------------------------------------------------------


class AlignedTurn(BaseModel):
    """All modality signals for a single turn, aligned by turn_index."""

    turn_index: int
    start_ms: int = 0
    end_ms: int = 0
    speaker: str = "student"

    # Content signals (may be empty for counsellor turns)
    hedging_markers: list[HedgingMarker] = Field(default_factory=list)
    agency_markers: list[AgencyMarker] = Field(default_factory=list)
    avoidance_events: list[AvoidanceEvent] = Field(default_factory=list)
    code_switch_events: list[CodeSwitchEvent] = Field(default_factory=list)
    topic_keys: list[str] = Field(default_factory=list)

    # Audio signals
    audio: TurnAudioFeatures | None = None

    # Video signals
    video: TurnVideoFeatures | None = None

    # Derived
    modalities_present: list[Modality] = Field(default_factory=list)


class AlignedWindow(BaseModel):
    """All modality signals for a topic window, aligned by window_id."""

    window: TopicWindow
    turn_indices: list[int] = Field(default_factory=list)

    # Content summary
    hedging_count: int = 0
    agency_markers: list[AgencyMarker] = Field(default_factory=list)
    avoidance_count: int = 0
    code_switch_count: int = 0

    # Audio summary
    audio_summary: WindowAudioSummary | None = None

    # Video summary
    video_summary: WindowVideoSummary | None = None

    modalities_present: list[Modality] = Field(default_factory=list)


class AlignedSession(BaseModel):
    """Session-level aligned output from all three modalities."""

    session_id: uuid.UUID
    turns: list[AlignedTurn] = Field(default_factory=list)
    windows: list[AlignedWindow] = Field(default_factory=list)
    observations: list[SignalObservation] = Field(default_factory=list)
    duration_ms: int = 0
    modalities_available: list[Modality] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Turn alignment
# ---------------------------------------------------------------------------


def _align_turns(
    session_id: uuid.UUID,
    turns_raw: Sequence[dict],
    content: ContentFeatures | None,
    audio: AudioFeatures | None,
    video: VideoFeatures | None,
) -> list[AlignedTurn]:
    """Build AlignedTurn objects by joining features across modalities."""

    # Build per-turn lookup maps
    audio_by_turn: dict[int, TurnAudioFeatures] = {}
    if audio:
        for tf in audio.turn_features:
            audio_by_turn[tf.turn_index] = tf

    video_by_turn: dict[int, TurnVideoFeatures] = {}
    if video:
        for tf in video.turn_features:
            video_by_turn[tf.turn_index] = tf

    # Content observations by turn
    hedging_by_turn: dict[int, list[HedgingMarker]] = {}
    agency_by_turn: dict[int, list[AgencyMarker]] = {}
    avoidance_by_turn: dict[int, list[AvoidanceEvent]] = {}
    codeswitch_by_turn: dict[int, list[CodeSwitchEvent]] = {}

    if content:
        for h in content.hedging_markers:
            hedging_by_turn.setdefault(h.turn_index, []).append(h)
        for a in content.agency_markers:
            agency_by_turn.setdefault(a.turn_index, []).append(a)
        for av in content.avoidance_events:
            avoidance_by_turn.setdefault(av.turn_index, []).append(av)
        for cs in content.code_switch_events:
            codeswitch_by_turn.setdefault(cs.turn_index, []).append(cs)

    # Topic membership by turn
    topics_by_turn: dict[int, list[str]] = {}
    if content:
        for topic in content.topics:
            for ti in topic.turn_indices:
                topics_by_turn.setdefault(ti, []).append(topic.topic_key)

    aligned: list[AlignedTurn] = []
    for turn in turns_raw:
        ti = turn["turn_index"]
        modalities: list[Modality] = []

        has_content = bool(
            hedging_by_turn.get(ti)
            or agency_by_turn.get(ti)
            or avoidance_by_turn.get(ti)
            or codeswitch_by_turn.get(ti)
            or topics_by_turn.get(ti)
        )
        if has_content:
            modalities.append(Modality.content)
        if ti in audio_by_turn:
            modalities.append(Modality.audio)
        if ti in video_by_turn:
            modalities.append(Modality.video)

        aligned.append(AlignedTurn(
            turn_index=ti,
            start_ms=turn.get("start_ms", 0),
            end_ms=turn.get("end_ms", 0),
            speaker=turn.get("speaker", "student"),
            hedging_markers=hedging_by_turn.get(ti, []),
            agency_markers=agency_by_turn.get(ti, []),
            avoidance_events=avoidance_by_turn.get(ti, []),
            code_switch_events=codeswitch_by_turn.get(ti, []),
            topic_keys=topics_by_turn.get(ti, []),
            audio=audio_by_turn.get(ti),
            video=video_by_turn.get(ti),
            modalities_present=modalities,
        ))

    return aligned


# ---------------------------------------------------------------------------
# Window alignment
# ---------------------------------------------------------------------------


def _align_windows(
    windows: list[TopicWindow],
    content: ContentFeatures | None,
    audio: AudioFeatures | None,
    video: VideoFeatures | None,
) -> list[AlignedWindow]:
    """Build AlignedWindow objects by joining window-level summaries."""

    # Audio window summaries by topic_key
    audio_win_map: dict[str, WindowAudioSummary] = {}
    if audio:
        for ws in audio.window_summaries:
            if ws.topic_key:
                audio_win_map[ws.topic_key] = ws

    # Video window summaries by topic_key
    video_win_map: dict[str, WindowVideoSummary] = {}
    if video:
        for ws in video.window_summaries:
            if ws.topic_key:
                video_win_map[ws.topic_key] = ws

    # Content observations indexed by turn for counting within windows
    hedging_turns: set[int] = set()
    avoidance_turns: set[int] = set()
    codeswitch_turns: set[int] = set()
    agency_by_turn: dict[int, list[AgencyMarker]] = {}

    if content:
        for h in content.hedging_markers:
            hedging_turns.add(h.turn_index)
        for av in content.avoidance_events:
            avoidance_turns.add(av.turn_index)
        for cs in content.code_switch_events:
            codeswitch_turns.add(cs.turn_index)
        for a in content.agency_markers:
            agency_by_turn.setdefault(a.turn_index, []).append(a)

    aligned: list[AlignedWindow] = []
    for win in windows:
        turn_set = set(win.source_turn_indices)
        modalities: list[Modality] = []

        # Content presence
        has_content = bool(
            turn_set & hedging_turns
            or turn_set & avoidance_turns
            or turn_set & codeswitch_turns
            or any(ti in agency_by_turn for ti in turn_set)
        )
        if has_content:
            modalities.append(Modality.content)

        audio_summary = audio_win_map.get(win.topic_key)
        if audio_summary:
            modalities.append(Modality.audio)

        video_summary = video_win_map.get(win.topic_key)
        if video_summary:
            modalities.append(Modality.video)

        # Count content signals in this window
        window_agency: list[AgencyMarker] = []
        for ti in turn_set:
            window_agency.extend(agency_by_turn.get(ti, []))

        aligned.append(AlignedWindow(
            window=win,
            turn_indices=win.source_turn_indices,
            hedging_count=len(turn_set & hedging_turns),
            agency_markers=window_agency,
            avoidance_count=len(turn_set & avoidance_turns),
            code_switch_count=len(turn_set & codeswitch_turns),
            audio_summary=audio_summary,
            video_summary=video_summary,
            modalities_present=modalities,
        ))

    return aligned


# ---------------------------------------------------------------------------
# Observation generation — flatten aligned data into SignalObservation list
# ---------------------------------------------------------------------------


def _generate_observations(
    session_id: uuid.UUID,
    aligned_turns: list[AlignedTurn],
    windows: list[TopicWindow],
    audio: AudioFeatures | None,
    video: VideoFeatures | None,
) -> list[SignalObservation]:
    """Generate unified SignalObservation records from all modalities.

    These map directly to the signal_observations DB table and are the
    primary input for the evidence graph builder.
    """
    observations: list[SignalObservation] = []

    # Window lookup: turn_index → window_id
    turn_to_window: dict[int, uuid.UUID] = {}
    for w in windows:
        for ti in w.source_turn_indices:
            if ti not in turn_to_window:
                turn_to_window[ti] = w.id

    for at in aligned_turns:
        wid = turn_to_window.get(at.turn_index)

        # -- Audio observations --
        if at.audio:
            a = at.audio
            if a.pitch_mean_hz is not None:
                observations.append(SignalObservation(
                    session_id=session_id,
                    window_id=wid,
                    turn_index=at.turn_index,
                    modality=Modality.audio,
                    signal_key="pitch",
                    value_json={
                        "mean_hz": a.pitch_mean_hz,
                        "std_hz": a.pitch_std_hz,
                    },
                    confidence=a.confidence_score or 0.5,
                    source=ObservationSource.deterministic,
                    timestamp_ms=a.start_ms,
                ))

            if a.speech_rate_wpm is not None:
                observations.append(SignalObservation(
                    session_id=session_id,
                    window_id=wid,
                    turn_index=at.turn_index,
                    modality=Modality.audio,
                    signal_key="speech_rate",
                    value_json={"wpm": a.speech_rate_wpm},
                    confidence=0.7,
                    source=ObservationSource.deterministic,
                    timestamp_ms=a.start_ms,
                ))

            if a.pause_count > 0:
                observations.append(SignalObservation(
                    session_id=session_id,
                    window_id=wid,
                    turn_index=at.turn_index,
                    modality=Modality.audio,
                    signal_key="pause_pattern",
                    value_json={
                        "count": a.pause_count,
                        "total_ms": a.pause_total_ms,
                    },
                    confidence=0.8,
                    source=ObservationSource.deterministic,
                    timestamp_ms=a.start_ms,
                ))

            if a.confidence_score is not None:
                observations.append(SignalObservation(
                    session_id=session_id,
                    window_id=wid,
                    turn_index=at.turn_index,
                    modality=Modality.audio,
                    signal_key="vocal_confidence",
                    value_json={"score": a.confidence_score},
                    confidence=0.6,
                    source=ObservationSource.model_inferred,
                    timestamp_ms=a.start_ms,
                ))

        # -- Video observations --
        if at.video:
            v = at.video
            observations.append(SignalObservation(
                session_id=session_id,
                window_id=wid,
                turn_index=at.turn_index,
                modality=Modality.video,
                signal_key="gaze",
                value_json={
                    "dominant": v.dominant_gaze.value,
                    "face_visible_pct": v.face_visible_pct,
                },
                confidence=0.65 if v.dominant_gaze != GazeDirection.unknown else 0.3,
                source=ObservationSource.model_inferred,
                timestamp_ms=at.start_ms,
            ))

            observations.append(SignalObservation(
                session_id=session_id,
                window_id=wid,
                turn_index=at.turn_index,
                modality=Modality.video,
                signal_key="engagement",
                value_json={"level": v.engagement_estimate.value},
                confidence=0.6,
                source=ObservationSource.model_inferred,
                timestamp_ms=at.start_ms,
            ))

            if v.tension_event_count > 0:
                observations.append(SignalObservation(
                    session_id=session_id,
                    window_id=wid,
                    turn_index=at.turn_index,
                    modality=Modality.video,
                    signal_key="facial_tension",
                    value_json={"event_count": v.tension_event_count},
                    confidence=0.55,
                    source=ObservationSource.model_inferred,
                    timestamp_ms=at.start_ms,
                ))

            if v.movement_event_count > 0:
                observations.append(SignalObservation(
                    session_id=session_id,
                    window_id=wid,
                    turn_index=at.turn_index,
                    modality=Modality.video,
                    signal_key="movement",
                    value_json={"event_count": v.movement_event_count},
                    confidence=0.55,
                    source=ObservationSource.model_inferred,
                    timestamp_ms=at.start_ms,
                ))

    return observations


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def align_session_signals(
    session_id: uuid.UUID,
    turns_raw: list[dict],
    topic_windows: list[TopicWindow],
    content: ContentFeatures | None = None,
    audio: AudioFeatures | None = None,
    video: VideoFeatures | None = None,
) -> AlignedSession:
    """Align content, audio, and video signals on a shared timeline.

    This is the main entry point for Task 9. Downstream consumers
    (evidence graph, correlator, hypotheses) operate on the returned
    ``AlignedSession``.

    Args:
        session_id: Session UUID.
        turns_raw: Raw turn dicts (turn_index, speaker, start_ms, end_ms, text).
        topic_windows: Pre-built topic windows from content extraction.
        content: Content features (may be None if extraction failed).
        audio: Audio features (may be None if no audio).
        video: Video features (may be None if no video).

    Returns:
        AlignedSession with per-turn, per-window, and observation data.
    """
    if not turns_raw:
        logger.warning("No turns provided for alignment — returning empty session")
        return AlignedSession(session_id=session_id)

    # Determine session duration
    duration_ms = 0
    if turns_raw:
        duration_ms = max(t.get("end_ms", 0) for t in turns_raw)

    # Which modalities are available?
    available: list[Modality] = []
    if content and (content.topics or content.hedging_markers):
        available.append(Modality.content)
    if audio and audio.turn_features:
        available.append(Modality.audio)
    if video and video.turn_features:
        available.append(Modality.video)

    # Align turns
    aligned_turns = _align_turns(session_id, turns_raw, content, audio, video)

    # Align windows
    aligned_windows = _align_windows(topic_windows, content, audio, video)

    # Generate unified observations
    observations = _generate_observations(
        session_id, aligned_turns, topic_windows, audio, video,
    )

    logger.info(
        "Session %s aligned: %d turns, %d windows, %d observations, modalities=%s",
        session_id,
        len(aligned_turns),
        len(aligned_windows),
        len(observations),
        [m.value for m in available],
    )

    return AlignedSession(
        session_id=session_id,
        turns=aligned_turns,
        windows=aligned_windows,
        observations=observations,
        duration_ms=duration_ms,
        modalities_available=available,
    )
