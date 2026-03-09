"""Video signal extractor — face presence, gaze, posture, tension, movement.

Replaces the legacy DeepFace-only analysis with a mixed pipeline:
  1. OpenCV frame extraction from video files
  2. MediaPipe Face Mesh for face detection + gaze proxy + tension
  3. MediaPipe Pose for posture/engagement + movement events
  4. Optional Gemini multimodal pass for richer engagement assessment
  5. Aggregation into per-turn and per-window summaries

Degrades gracefully when face is missing, video quality is poor,
or the video file itself is absent.
"""

from __future__ import annotations

import base64
import json
import logging
import math
import uuid
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from counselai.ingest.artifact_store import ArtifactStore
from counselai.settings import settings
from counselai.signals.video.schemas import (
    EngagementLevel,
    FacePresenceSegment,
    GazeDirection,
    GazeObservation,
    MovementEvent,
    MovementType,
    TensionEvent,
    TurnVideoFeatures,
    VideoFeatures,
    WindowVideoSummary,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

FRAME_SAMPLE_INTERVAL_SEC = 1.0  # sample 1 frame per second
GEMINI_SAMPLE_INTERVAL_SEC = 5.0  # Gemini gets 1 frame every 5 seconds
MIN_FACE_CONFIDENCE = 0.5
BLUR_VARIANCE_THRESHOLD = 25.0
POSE_VISIBILITY_THRESHOLD = 0.5

# Landmark indices for MediaPipe Face Mesh (468 landmarks)
# Eye iris centers for gaze estimation
LEFT_IRIS_CENTER = 468  # mediapipe iris landmark
RIGHT_IRIS_CENTER = 473
LEFT_EYE_INNER = 133
LEFT_EYE_OUTER = 33
RIGHT_EYE_INNER = 362
RIGHT_EYE_OUTER = 263
NOSE_TIP = 1

# Brow/jaw tension landmarks
LEFT_BROW_INNER = 107
RIGHT_BROW_INNER = 336
LEFT_BROW_OUTER = 70
RIGHT_BROW_OUTER = 300
JAW_TIP = 152
JAW_LEFT = 234
JAW_RIGHT = 454
UPPER_LIP = 13
LOWER_LIP = 14

# Pose landmarks (MediaPipe)
LEFT_SHOULDER = 11
RIGHT_SHOULDER = 12
LEFT_HIP = 23
RIGHT_HIP = 24
NOSE_POSE = 0


# ---------------------------------------------------------------------------
# MediaPipe helpers (lazy init to avoid import cost when not needed)
# ---------------------------------------------------------------------------

_face_mesh = None
_pose = None


def _get_face_mesh():
    """Lazy-init MediaPipe Face Mesh."""
    global _face_mesh
    if _face_mesh is None:
        import mediapipe as mp
        _face_mesh = mp.solutions.face_mesh.FaceMesh(
            static_image_mode=True,
            max_num_faces=1,
            refine_landmarks=True,  # enables iris landmarks
            min_detection_confidence=MIN_FACE_CONFIDENCE,
        )
    return _face_mesh


def _get_pose():
    """Lazy-init MediaPipe Pose."""
    global _pose
    if _pose is None:
        import mediapipe as mp
        _pose = mp.solutions.pose.Pose(
            static_image_mode=True,
            model_complexity=1,
            min_detection_confidence=0.5,
        )
    return _pose


# ---------------------------------------------------------------------------
# Frame extraction
# ---------------------------------------------------------------------------


def extract_frames(
    video_path: str | Path,
    interval_sec: float = FRAME_SAMPLE_INTERVAL_SEC,
) -> list[tuple[int, np.ndarray]]:
    """Extract frames at regular intervals. Returns list of (timestamp_ms, frame)."""
    video_path = str(video_path)
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        logger.error("Cannot open video: %s", video_path)
        return []

    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    frame_interval = max(1, int(fps * interval_sec))

    frames: list[tuple[int, np.ndarray]] = []
    frame_idx = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            break
        if frame_idx % frame_interval == 0:
            timestamp_ms = int((frame_idx / fps) * 1000)
            frames.append((timestamp_ms, frame))
        frame_idx += 1

    cap.release()
    logger.info(
        "Extracted %d frames from %s (total=%d, fps=%.1f)",
        len(frames), video_path, total_frames, fps,
    )
    return frames


def _is_blurry(frame: np.ndarray) -> bool:
    """Check if a frame is too blurry for reliable analysis."""
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    return bool(cv2.Laplacian(gray, cv2.CV_64F).var() < BLUR_VARIANCE_THRESHOLD)


def _video_duration_ms(video_path: str | Path) -> int | None:
    """Get video duration in milliseconds."""
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        return None
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()
    if fps > 0 and total > 0:
        return int((total / fps) * 1000)
    return None


# ---------------------------------------------------------------------------
# Face mesh analysis
# ---------------------------------------------------------------------------


def _analyze_face(frame: np.ndarray) -> dict[str, Any] | None:
    """Run face mesh on a single frame.

    Returns dict with: face_detected, face_confidence, gaze_direction,
    gaze_confidence, tension_regions, or None on failure.
    """
    mesh = _get_face_mesh()
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    results = mesh.process(rgb)

    if not results.multi_face_landmarks:
        return {"face_detected": False}

    landmarks = results.multi_face_landmarks[0].landmark
    h, w = frame.shape[:2]

    # --- Gaze estimation ---
    gaze_dir, gaze_conf = _estimate_gaze(landmarks, w, h)

    # --- Tension estimation ---
    tension_regions = _estimate_tension(landmarks, h)

    return {
        "face_detected": True,
        "face_confidence": 0.85,  # MediaPipe doesn't expose per-frame confidence directly
        "gaze_direction": gaze_dir,
        "gaze_confidence": gaze_conf,
        "tension_regions": tension_regions,
    }


def _estimate_gaze(landmarks, w: int, h: int) -> tuple[GazeDirection, float]:
    """Estimate gaze direction from iris + eye corner positions."""
    try:
        # Use iris landmarks if available (refine_landmarks=True)
        if len(landmarks) > RIGHT_IRIS_CENTER:
            l_iris = landmarks[LEFT_IRIS_CENTER]
            r_iris = landmarks[RIGHT_IRIS_CENTER]
        else:
            # Fallback to eye center approximation
            l_inner = landmarks[LEFT_EYE_INNER]
            l_outer = landmarks[LEFT_EYE_OUTER]
            l_iris_x = (l_inner.x + l_outer.x) / 2
            l_iris_y = (l_inner.y + l_outer.y) / 2

            r_inner = landmarks[RIGHT_EYE_INNER]
            r_outer = landmarks[RIGHT_EYE_OUTER]
            r_iris_x = (r_inner.x + r_outer.x) / 2
            r_iris_y = (r_inner.y + r_outer.y) / 2

            class _Pt:
                def __init__(self, x, y):
                    self.x, self.y = x, y

            l_iris = _Pt(l_iris_x, l_iris_y)
            r_iris = _Pt(r_iris_x, r_iris_y)

        # Compute iris position relative to eye corners (horizontal ratio)
        l_inner = landmarks[LEFT_EYE_INNER]
        l_outer = landmarks[LEFT_EYE_OUTER]
        r_inner = landmarks[RIGHT_EYE_INNER]
        r_outer = landmarks[RIGHT_EYE_OUTER]

        # Horizontal ratio: 0 = looking at outer corner, 1 = inner corner
        l_range = l_inner.x - l_outer.x
        r_range = r_inner.x - r_outer.x

        if abs(l_range) < 1e-6 or abs(r_range) < 1e-6:
            return GazeDirection.unknown, 0.3

        l_ratio = (l_iris.x - l_outer.x) / l_range
        r_ratio = (r_iris.x - r_outer.x) / r_range
        avg_h_ratio = (l_ratio + r_ratio) / 2

        # Vertical: compare iris y to eye center y
        l_center_y = (l_inner.y + l_outer.y) / 2
        r_center_y = (r_inner.y + r_outer.y) / 2
        l_v_offset = l_iris.y - l_center_y
        r_v_offset = r_iris.y - r_center_y
        avg_v_offset = (l_v_offset + r_v_offset) / 2

        # Classify
        confidence = 0.7

        if avg_v_offset > 0.015:
            return GazeDirection.downward, confidence
        if avg_v_offset < -0.015:
            return GazeDirection.upward, confidence

        if 0.35 < avg_h_ratio < 0.65:
            return GazeDirection.direct, min(0.9, confidence + 0.15)
        elif avg_h_ratio <= 0.35:
            return GazeDirection.averted_left, confidence
        else:
            return GazeDirection.averted_right, confidence

    except (IndexError, AttributeError):
        return GazeDirection.unknown, 0.2


def _estimate_tension(landmarks, h: int) -> list[dict[str, Any]]:
    """Estimate facial tension from landmark distances (brow furrow, jaw clench, lip press)."""
    regions = []

    try:
        # Brow furrow: distance between inner brow points
        l_brow = landmarks[LEFT_BROW_INNER]
        r_brow = landmarks[RIGHT_BROW_INNER]
        brow_dist = abs(l_brow.x - r_brow.x)

        # Baseline brow distance is roughly 0.08-0.12 of face width
        # Furrowed = narrower distance
        if brow_dist < 0.07:
            intensity = min(1.0, (0.07 - brow_dist) / 0.04)
            regions.append({
                "region": "brow",
                "intensity": round(intensity, 2),
                "confidence": 0.6,
            })

        # Jaw clench: vertical distance between jaw and lip
        jaw = landmarks[JAW_TIP]
        lower_lip = landmarks[LOWER_LIP]
        jaw_lip_dist = abs(jaw.y - lower_lip.y)

        # Tight jaw = smaller distance
        if jaw_lip_dist < 0.04:
            intensity = min(1.0, (0.04 - jaw_lip_dist) / 0.03)
            regions.append({
                "region": "jaw",
                "intensity": round(intensity, 2),
                "confidence": 0.55,
            })

        # Lip press: distance between upper and lower lip
        upper_lip = landmarks[UPPER_LIP]
        lip_dist = abs(upper_lip.y - lower_lip.y)

        if lip_dist < 0.008:
            intensity = min(1.0, (0.008 - lip_dist) / 0.006)
            regions.append({
                "region": "mouth",
                "intensity": round(intensity, 2),
                "confidence": 0.5,
            })

    except (IndexError, AttributeError):
        pass

    return regions


# ---------------------------------------------------------------------------
# Pose analysis
# ---------------------------------------------------------------------------


def _analyze_pose(frame: np.ndarray) -> dict[str, Any] | None:
    """Run pose estimation on a single frame.

    Returns posture metrics and movement-relevant measurements.
    """
    pose = _get_pose()
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    results = pose.process(rgb)

    if not results.pose_landmarks:
        return None

    lm = results.pose_landmarks.landmark

    try:
        # Shoulder midpoint
        l_sh = lm[LEFT_SHOULDER]
        r_sh = lm[RIGHT_SHOULDER]

        if (l_sh.visibility < POSE_VISIBILITY_THRESHOLD
                or r_sh.visibility < POSE_VISIBILITY_THRESHOLD):
            return None

        shoulder_mid_y = (l_sh.y + r_sh.y) / 2
        shoulder_width = abs(l_sh.x - r_sh.x)

        # Head position relative to shoulders (lean detection)
        nose = lm[NOSE_POSE]
        shoulder_mid_x = (l_sh.x + r_sh.x) / 2

        # Vertical lean: nose Y vs shoulder midpoint Y
        vertical_offset = shoulder_mid_y - nose.y  # positive = upright

        # Horizontal lean
        horizontal_offset = nose.x - shoulder_mid_x

        return {
            "shoulder_mid_y": shoulder_mid_y,
            "shoulder_width": shoulder_width,
            "vertical_offset": vertical_offset,
            "horizontal_offset": horizontal_offset,
            "nose_y": nose.y,
            "nose_x": nose.x,
        }

    except (IndexError, AttributeError):
        return None


def _classify_engagement(
    face_result: dict | None,
    pose_result: dict | None,
) -> EngagementLevel:
    """Combine face and pose signals into an engagement estimate."""
    score = 0.5  # baseline: passive

    if face_result and face_result.get("face_detected"):
        gaze = face_result.get("gaze_direction", GazeDirection.unknown)
        if gaze == GazeDirection.direct:
            score += 0.25
        elif gaze in (GazeDirection.averted_left, GazeDirection.averted_right):
            score -= 0.1
        elif gaze == GazeDirection.downward:
            score -= 0.15
    else:
        score -= 0.2  # no face = likely disengaged

    if pose_result:
        v_offset = pose_result.get("vertical_offset", 0)
        # Leaning forward = more engaged
        if v_offset > 0.22:
            score += 0.15  # upright / leaning forward
        elif v_offset < 0.15:
            score -= 0.1  # slouching

    if score >= 0.8:
        return EngagementLevel.highly_engaged
    elif score >= 0.55:
        return EngagementLevel.engaged
    elif score >= 0.35:
        return EngagementLevel.passive
    else:
        return EngagementLevel.disengaged


# ---------------------------------------------------------------------------
# Movement detection (across consecutive frames)
# ---------------------------------------------------------------------------


def _detect_movements(
    pose_history: list[tuple[int, dict]],
) -> list[MovementEvent]:
    """Detect movement events from pose measurement history.

    pose_history: list of (timestamp_ms, pose_result) pairs.
    """
    events: list[MovementEvent] = []
    if len(pose_history) < 2:
        return events

    for i in range(1, len(pose_history)):
        t_prev, p_prev = pose_history[i - 1]
        t_curr, p_curr = pose_history[i]

        if p_prev is None or p_curr is None:
            continue

        # Vertical change (lean forward/back)
        v_delta = p_curr["vertical_offset"] - p_prev["vertical_offset"]
        if abs(v_delta) > 0.04:
            mv_type = MovementType.lean_forward if v_delta > 0 else MovementType.lean_back
            events.append(MovementEvent(
                start_ms=t_prev,
                end_ms=t_curr,
                movement_type=mv_type,
                magnitude=round(min(1.0, abs(v_delta) / 0.1), 2),
                confidence=0.65,
            ))

        # Horizontal head movement
        h_delta = p_curr["horizontal_offset"] - p_prev["horizontal_offset"]
        if abs(h_delta) > 0.05:
            events.append(MovementEvent(
                start_ms=t_prev,
                end_ms=t_curr,
                movement_type=MovementType.head_turn,
                magnitude=round(min(1.0, abs(h_delta) / 0.12), 2),
                confidence=0.6,
            ))

        # Shoulder width change (posture shift)
        sw_delta = abs(p_curr["shoulder_width"] - p_prev["shoulder_width"])
        if sw_delta > 0.03:
            events.append(MovementEvent(
                start_ms=t_prev,
                end_ms=t_curr,
                movement_type=MovementType.posture_shift,
                magnitude=round(min(1.0, sw_delta / 0.08), 2),
                confidence=0.55,
            ))

    # Detect fidgeting: rapid small movements in a window
    if len(events) >= 3:
        window_ms = 10_000  # 10 second windows
        i = 0
        while i < len(events):
            window_start = events[i].start_ms
            window_events = [
                e for e in events
                if window_start <= e.start_ms < window_start + window_ms
            ]
            if len(window_events) >= 4:
                events.append(MovementEvent(
                    start_ms=window_start,
                    end_ms=window_start + window_ms,
                    movement_type=MovementType.fidgeting,
                    magnitude=round(min(1.0, len(window_events) / 8), 2),
                    confidence=0.5,
                ))
            i += max(1, len(window_events))

    return events


# ---------------------------------------------------------------------------
# Gemini multimodal frame analysis
# ---------------------------------------------------------------------------


def _gemini_analyze_frames(
    frames: list[tuple[int, np.ndarray]],
    sample_interval_sec: float = GEMINI_SAMPLE_INTERVAL_SEC,
) -> list[dict[str, Any]]:
    """Use Gemini vision to analyze sampled frames for engagement & tension.

    Returns a list of observation dicts with timestamp_ms, engagement,
    tension_notes, and other high-level observations.
    """
    if not settings.gemini_api_key:
        logger.warning("No Gemini API key — skipping multimodal frame analysis")
        return []

    try:
        from google import genai
        from google.genai import types
    except ImportError:
        logger.warning("google-genai not installed — skipping Gemini frame analysis")
        return []

    client = genai.Client(api_key=settings.gemini_api_key)

    # Sample frames at a lower rate for Gemini (cost control)
    fps_approx = 1.0 / FRAME_SAMPLE_INTERVAL_SEC if FRAME_SAMPLE_INTERVAL_SEC > 0 else 1
    gemini_interval = max(1, int(sample_interval_sec * fps_approx))

    sampled = frames[::gemini_interval]
    if not sampled:
        return []

    # Limit to max 20 frames to control cost
    if len(sampled) > 20:
        step = len(sampled) // 20
        sampled = sampled[::step][:20]

    observations = []
    prompt = (
        "You are analyzing a frame from a student counselling video session. "
        "Assess the student's visible state. Return ONLY valid JSON with these fields:\n"
        '{"engagement": "disengaged|passive|engaged|highly_engaged", '
        '"tension_visible": true/false, '
        '"tension_regions": ["brow"|"jaw"|"mouth"|"eye"], '
        '"posture": "upright|slouched|leaning_forward|leaning_back", '
        '"notable": "brief free-text note or null"}\n'
        "Be conservative. If unsure, use passive/false."
    )

    for ts_ms, frame in sampled:
        try:
            # Encode frame as JPEG
            _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
            img_bytes = buf.tobytes()

            response = client.models.generate_content(
                model=settings.gemini_synthesis_model,
                contents=[
                    types.Content(
                        parts=[
                            types.Part.from_bytes(data=img_bytes, mime_type="image/jpeg"),
                            types.Part.from_text(text=prompt),
                        ]
                    )
                ],
                config=types.GenerateContentConfig(
                    temperature=0.1,
                    max_output_tokens=256,
                ),
            )

            text = response.text.strip()
            # Strip markdown fences if present
            if text.startswith("```"):
                text = text.split("\n", 1)[-1]
            if text.endswith("```"):
                text = text.rsplit("```", 1)[0]
            text = text.strip()

            parsed = json.loads(text)
            parsed["timestamp_ms"] = ts_ms
            observations.append(parsed)

        except (json.JSONDecodeError, Exception) as exc:
            logger.debug("Gemini frame analysis failed at %dms: %s", ts_ms, exc)
            continue

    logger.info("Gemini analyzed %d/%d sampled frames", len(observations), len(sampled))
    return observations


# ---------------------------------------------------------------------------
# Turn/window alignment
# ---------------------------------------------------------------------------


def _find_turn_index(timestamp_ms: int, turns: list[dict]) -> int | None:
    """Find which turn a timestamp falls within."""
    for t in turns:
        if t["start_ms"] <= timestamp_ms <= t["end_ms"]:
            return t["turn_index"]
    return None


def _build_turn_features(
    turns: list[dict],
    face_segments: list[FacePresenceSegment],
    gaze_obs: list[GazeObservation],
    tension_events: list[TensionEvent],
    movement_events: list[MovementEvent],
    engagement_map: dict[int, EngagementLevel],
) -> list[TurnVideoFeatures]:
    """Aggregate frame-level signals into per-turn features."""
    turn_features = []

    for turn in turns:
        ti = turn["turn_index"]
        t_start = turn["start_ms"]
        t_end = turn["end_ms"]
        duration = max(1, t_end - t_start)

        # Face visibility in this turn
        visible_ms = 0
        for seg in face_segments:
            if seg.end_ms <= t_start or seg.start_ms >= t_end:
                continue
            overlap_start = max(seg.start_ms, t_start)
            overlap_end = min(seg.end_ms, t_end)
            if seg.face_detected:
                visible_ms += overlap_end - overlap_start

        face_pct = min(100.0, (visible_ms / duration) * 100)

        # Dominant gaze
        turn_gazes = [g for g in gaze_obs if g.turn_index == ti]
        if turn_gazes:
            gaze_counts: dict[GazeDirection, int] = {}
            for g in turn_gazes:
                gaze_counts[g.direction] = gaze_counts.get(g.direction, 0) + 1
            dominant_gaze = max(gaze_counts, key=gaze_counts.get)
        else:
            dominant_gaze = GazeDirection.unknown

        # Count events in turn
        t_tension = sum(1 for e in tension_events if e.turn_index == ti)
        t_movement = sum(
            1 for e in movement_events
            if e.start_ms >= t_start and e.start_ms < t_end
        )

        engagement = engagement_map.get(ti, EngagementLevel.passive)

        turn_features.append(TurnVideoFeatures(
            turn_index=ti,
            start_ms=t_start,
            end_ms=t_end,
            face_visible_pct=round(face_pct, 1),
            dominant_gaze=dominant_gaze,
            engagement_estimate=engagement,
            tension_event_count=t_tension,
            movement_event_count=t_movement,
        ))

    return turn_features


def _build_window_summaries(
    windows: list[dict],
    turn_features: list[TurnVideoFeatures],
    tension_events: list[TensionEvent],
    movement_events: list[MovementEvent],
) -> list[WindowVideoSummary]:
    """Aggregate turn features into per-window summaries."""
    summaries = []

    for win in windows:
        w_start = win["start_ms"]
        w_end = win["end_ms"]
        duration_min = max(0.001, (w_end - w_start) / 60_000)

        # Find turns in this window
        win_turns = [
            tf for tf in turn_features
            if tf.start_ms < w_end and tf.end_ms > w_start
        ]

        if not win_turns:
            summaries.append(WindowVideoSummary(
                window_id=win.get("id"),
                topic_key=win.get("topic_key"),
                start_ms=w_start,
                end_ms=w_end,
            ))
            continue

        avg_face = sum(t.face_visible_pct for t in win_turns) / len(win_turns)

        # Dominant gaze across window
        gaze_counts: dict[GazeDirection, int] = {}
        for t in win_turns:
            gaze_counts[t.dominant_gaze] = gaze_counts.get(t.dominant_gaze, 0) + 1
        dom_gaze = max(gaze_counts, key=gaze_counts.get)

        # Dominant engagement
        eng_counts: dict[EngagementLevel, int] = {}
        for t in win_turns:
            eng_counts[t.engagement_estimate] = eng_counts.get(t.engagement_estimate, 0) + 1
        dom_eng = max(eng_counts, key=eng_counts.get)

        # Event densities
        w_tension = sum(
            1 for e in tension_events
            if w_start <= e.timestamp_ms < w_end
        )
        w_movement = sum(
            1 for e in movement_events
            if w_start <= e.start_ms < w_end
        )

        summaries.append(WindowVideoSummary(
            window_id=win.get("id"),
            topic_key=win.get("topic_key"),
            start_ms=w_start,
            end_ms=w_end,
            avg_face_visible_pct=round(avg_face, 1),
            dominant_gaze=dom_gaze,
            engagement_estimate=dom_eng,
            tension_density=round(w_tension / duration_min, 2),
            movement_density=round(w_movement / duration_min, 2),
        ))

    return summaries


# ---------------------------------------------------------------------------
# Reliability scoring
# ---------------------------------------------------------------------------


def _compute_reliability(
    total_frames: int,
    usable_frames: int,
    face_detected_frames: int,
    blurry_frames: int,
    video_duration_ms: int | None,
) -> float:
    """Score overall video signal reliability 0-1."""
    if total_frames == 0:
        return 0.0

    usable_ratio = usable_frames / total_frames
    face_ratio = face_detected_frames / max(1, usable_frames)
    blur_ratio = blurry_frames / total_frames

    # Weighted combination
    score = (
        0.3 * usable_ratio
        + 0.4 * face_ratio
        + 0.2 * (1.0 - blur_ratio)
        + 0.1 * (1.0 if video_duration_ms and video_duration_ms > 30_000 else 0.5)
    )
    return round(max(0.0, min(1.0, score)), 2)


# ---------------------------------------------------------------------------
# Main extractor
# ---------------------------------------------------------------------------


def extract_video_signals(
    session_id: str,
    video_path: str | Path | None = None,
    turns: list[dict] | None = None,
    topic_windows: list[dict] | None = None,
    use_gemini: bool = True,
    artifact_store: ArtifactStore | None = None,
) -> VideoFeatures:
    """Run the full video signal extraction pipeline.

    Args:
        session_id: Session UUID string.
        video_path: Path to video file. If None, tries standard artifact location.
        turns: List of turn dicts with turn_index, start_ms, end_ms.
        topic_windows: List of topic window dicts for window-level aggregation.
        use_gemini: Whether to run Gemini multimodal analysis.
        artifact_store: ArtifactStore instance (created if not provided).

    Returns:
        VideoFeatures with all extracted signals, or empty features on failure.
    """
    store = artifact_store or ArtifactStore()
    sid = str(session_id)
    turns = turns or []
    topic_windows = topic_windows or []

    # Resolve video path
    if video_path is None:
        for candidate in ["video.raw.webm", "video.webm", "video.mp4"]:
            candidate_path = store.session_dir(sid) / candidate
            if candidate_path.exists():
                video_path = candidate_path
                break

    if video_path is None or not Path(video_path).exists():
        logger.warning("No video file found for session %s — returning empty features", sid)
        return VideoFeatures(
            session_id=uuid.UUID(sid),
            reliability_score=0.0,
        )

    video_path = Path(video_path)
    duration_ms = _video_duration_ms(video_path)

    # --- Extract frames ---
    frames = extract_frames(video_path, FRAME_SAMPLE_INTERVAL_SEC)
    if not frames:
        logger.warning("No frames extracted from %s", video_path)
        return VideoFeatures(
            session_id=uuid.UUID(sid),
            video_duration_ms=duration_ms,
            reliability_score=0.0,
        )

    total_frames = len(frames)
    blurry_count = 0
    usable_frames_data: list[tuple[int, np.ndarray]] = []

    for ts, frame in frames:
        if _is_blurry(frame):
            blurry_count += 1
        else:
            usable_frames_data.append((ts, frame))

    # If all frames blurry, use top least-blurry ones
    if not usable_frames_data and frames:
        logger.warning("All frames blurry — using least-blurry subset")
        scored = [
            (ts, f, cv2.Laplacian(cv2.cvtColor(f, cv2.COLOR_BGR2GRAY), cv2.CV_64F).var())
            for ts, f in frames
        ]
        scored.sort(key=lambda x: x[2], reverse=True)
        usable_frames_data = [(ts, f) for ts, f, _ in scored[:max(5, len(scored) // 4)]]
        blurry_count = total_frames - len(usable_frames_data)

    # --- Per-frame analysis ---
    face_segments: list[FacePresenceSegment] = []
    gaze_observations: list[GazeObservation] = []
    tension_events: list[TensionEvent] = []
    pose_history: list[tuple[int, dict | None]] = []
    engagement_by_timestamp: dict[int, EngagementLevel] = {}
    face_detected_count = 0

    prev_face_state: bool | None = None
    segment_start_ms: int = 0

    for ts_ms, frame in usable_frames_data:
        # Face analysis
        face_result = _analyze_face(frame)

        if face_result is None:
            face_detected = False
        else:
            face_detected = face_result.get("face_detected", False)

        if face_detected:
            face_detected_count += 1

        # Build face presence segments (merge contiguous same-state frames)
        if prev_face_state is None:
            prev_face_state = face_detected
            segment_start_ms = ts_ms
        elif face_detected != prev_face_state:
            face_segments.append(FacePresenceSegment(
                start_ms=segment_start_ms,
                end_ms=ts_ms,
                face_detected=prev_face_state,
                face_confidence=0.85 if prev_face_state else 0.0,
            ))
            prev_face_state = face_detected
            segment_start_ms = ts_ms

        # Gaze
        if face_result and face_detected:
            gaze_dir = face_result.get("gaze_direction", GazeDirection.unknown)
            gaze_conf = face_result.get("gaze_confidence", 0.3)
            turn_idx = _find_turn_index(ts_ms, turns)

            gaze_observations.append(GazeObservation(
                start_ms=ts_ms,
                end_ms=ts_ms + int(FRAME_SAMPLE_INTERVAL_SEC * 1000),
                direction=gaze_dir,
                turn_index=turn_idx,
                confidence=gaze_conf,
            ))

            # Tension events
            for region_data in face_result.get("tension_regions", []):
                tension_events.append(TensionEvent(
                    timestamp_ms=ts_ms,
                    turn_index=turn_idx,
                    region=region_data["region"],
                    intensity=region_data["intensity"],
                    confidence=region_data["confidence"],
                ))

        # Pose analysis
        pose_result = _analyze_pose(frame)
        pose_history.append((ts_ms, pose_result))

        # Engagement estimate
        engagement = _classify_engagement(face_result, pose_result)
        engagement_by_timestamp[ts_ms] = engagement

    # Close final face segment
    if prev_face_state is not None and usable_frames_data:
        last_ts = usable_frames_data[-1][0]
        face_segments.append(FacePresenceSegment(
            start_ms=segment_start_ms,
            end_ms=last_ts + int(FRAME_SAMPLE_INTERVAL_SEC * 1000),
            face_detected=prev_face_state,
            face_confidence=0.85 if prev_face_state else 0.0,
        ))

    # --- Movement detection ---
    movement_events = _detect_movements(pose_history)

    # Assign turn indices to movement events
    for evt in movement_events:
        evt.turn_index = _find_turn_index(evt.start_ms, turns)

    # --- Gemini multimodal pass ---
    gemini_observations: list[dict] = []
    if use_gemini and settings.gemini_api_key:
        try:
            gemini_observations = _gemini_analyze_frames(usable_frames_data)
        except Exception as exc:
            logger.error("Gemini frame analysis failed: %s", exc)

    # Merge Gemini engagement signals (override deterministic where available)
    engagement_map_by_turn: dict[int, EngagementLevel] = {}
    for ts_ms, eng in engagement_by_timestamp.items():
        ti = _find_turn_index(ts_ms, turns)
        if ti is not None and ti not in engagement_map_by_turn:
            engagement_map_by_turn[ti] = eng

    # Gemini can override engagement estimates
    eng_str_to_level = {
        "disengaged": EngagementLevel.disengaged,
        "passive": EngagementLevel.passive,
        "engaged": EngagementLevel.engaged,
        "highly_engaged": EngagementLevel.highly_engaged,
    }
    for obs in gemini_observations:
        ts = obs.get("timestamp_ms", 0)
        ti = _find_turn_index(ts, turns)
        eng_str = obs.get("engagement", "")
        if ti is not None and eng_str in eng_str_to_level:
            engagement_map_by_turn[ti] = eng_str_to_level[eng_str]

        # Add Gemini-detected tension
        if obs.get("tension_visible") and obs.get("tension_regions"):
            for region in obs["tension_regions"]:
                if region in ("brow", "jaw", "mouth", "eye"):
                    tension_events.append(TensionEvent(
                        timestamp_ms=ts,
                        turn_index=ti,
                        region=region,
                        intensity=0.6,  # Gemini doesn't give intensity, use moderate
                        confidence=0.7,
                    ))

    # --- Aggregate per turn ---
    turn_features = _build_turn_features(
        turns, face_segments, gaze_observations,
        tension_events, movement_events, engagement_map_by_turn,
    )

    # --- Aggregate per window ---
    window_summaries = _build_window_summaries(
        topic_windows, turn_features, tension_events, movement_events,
    )

    # --- Session-wide metrics ---
    total_face_visible_pct = 0.0
    if face_segments:
        total_duration = sum(
            (s.end_ms - s.start_ms) for s in face_segments
        )
        face_visible_duration = sum(
            (s.end_ms - s.start_ms) for s in face_segments if s.face_detected
        )
        if total_duration > 0:
            total_face_visible_pct = round(
                (face_visible_duration / total_duration) * 100, 1
            )

    reliability = _compute_reliability(
        total_frames=total_frames,
        usable_frames=len(usable_frames_data),
        face_detected_frames=face_detected_count,
        blurry_frames=blurry_count,
        video_duration_ms=duration_ms,
    )

    features = VideoFeatures(
        session_id=uuid.UUID(sid),
        face_presence=face_segments,
        gaze_observations=gaze_observations,
        tension_events=tension_events,
        movement_events=movement_events,
        turn_features=turn_features,
        window_summaries=window_summaries,
        total_face_visible_pct=total_face_visible_pct,
        video_duration_ms=duration_ms,
        frame_count=total_frames,
        reliability_score=reliability,
    )

    # --- Persist to artifact store ---
    try:
        store.write_json(
            sid,
            "features/video.json",
            features.model_dump(mode="json"),
        )
        logger.info(
            "Video features saved for session %s: %d frames, reliability=%.2f",
            sid, total_frames, reliability,
        )
    except Exception as exc:
        logger.error("Failed to save video features: %s", exc)

    return features
