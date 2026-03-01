"""Facial expression analysis using DeepFace."""
from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional

import cv2
import numpy as np
from deepface import DeepFace


BLUR_THRESHOLD = 100.0
FRAME_INTERVAL_SECONDS = 2


def _is_blurry(image: np.ndarray) -> bool:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    variance = cv2.Laplacian(gray, cv2.CV_64F).var()
    return variance < BLUR_THRESHOLD


def _extract_frame_index(filename: str) -> Optional[int]:
    match = re.search(r"(\d+)", filename)
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def _frame_timestamp(filename: str, fallback_index: int) -> int:
    index = _extract_frame_index(filename)
    if index is None:
        index = fallback_index + 1
    return (index - 1) * FRAME_INTERVAL_SECONDS


def _normalize_confidence(value: float) -> float:
    if value > 1.0:
        return value / 100.0
    return float(max(0.0, min(1.0, value)))


def analyze_single_frame(frame_path: str) -> Dict[str, Any]:
    """Analyze one frame and return basic emotion info."""
    print(f"[face_analyzer] Analyzing single frame: {frame_path}")
    if not os.path.exists(frame_path):
        print("[face_analyzer] Error: frame not found")
        return {}

    try:
        result = DeepFace.analyze(
            img_path=frame_path,
            actions=["emotion"],
            enforce_detection=False,
            detector_backend="opencv",
        )
    except Exception as exc:
        print(f"[face_analyzer] Error: DeepFace failure ({exc})")
        return {}

    if isinstance(result, list):
        result = result[0] if result else {}

    emotions = result.get("emotion", {}) if isinstance(result, dict) else {}
    dominant_emotion = result.get("dominant_emotion", "unknown")
    confidence = 0.0
    if dominant_emotion in emotions:
        confidence = _normalize_confidence(float(emotions[dominant_emotion]))

    return {
        "dominant_emotion": dominant_emotion,
        "emotions": emotions,
        "confidence": confidence,
    }


def analyze_frames(frames_dir: str) -> Dict[str, Any]:
    """Analyze a directory of frames for emotion timeline and summary stats."""
    print(f"[face_analyzer] Starting frame analysis in {frames_dir}")

    if not os.path.isdir(frames_dir):
        print("[face_analyzer] Error: frames_dir not found")
        return {}

    frame_files = sorted(
        f
        for f in os.listdir(frames_dir)
        if f.lower().endswith((".jpg", ".jpeg", ".png"))
    )

    if not frame_files:
        print("[face_analyzer] Error: no frames found")
        return {}

    timeline: List[Dict[str, Any]] = []
    emotions_sum: Dict[str, float] = {}
    dominant_emotions: List[str] = []
    eye_contact_scores: List[float] = []
    facial_tension_scores: List[float] = []
    smile_count = 0
    previous_happy = False

    for idx, filename in enumerate(frame_files):
        frame_path = os.path.join(frames_dir, filename)
        try:
            image = cv2.imread(frame_path)
            if image is None:
                print(f"[face_analyzer] Warning: unreadable frame {filename}")
                continue

            if _is_blurry(image):
                print(f"[face_analyzer] Warning: blurry frame {filename}")
                continue

            analysis = DeepFace.analyze(
                img_path=frame_path,
                actions=["emotion"],
                enforce_detection=False,
                detector_backend="opencv",
            )

            if isinstance(analysis, list):
                analysis = analysis[0] if analysis else {}

            if not analysis or "emotion" not in analysis:
                print(f"[face_analyzer] Warning: no face detected in {filename}")
                continue

            emotions = analysis.get("emotion", {})
            dominant_emotion = analysis.get("dominant_emotion", "unknown")
            confidence = _normalize_confidence(float(emotions.get(dominant_emotion, 0.0)))
            timestamp = _frame_timestamp(filename, idx)

            timeline.append(
                {
                    "timestamp": timestamp,
                    "dominant_emotion": dominant_emotion,
                    "emotions": emotions,
                    "confidence": confidence,
                }
            )

            dominant_emotions.append(dominant_emotion)

            for emotion, value in emotions.items():
                emotions_sum[emotion] = emotions_sum.get(emotion, 0.0) + float(value)

            face_confidence = _normalize_confidence(float(analysis.get("face_confidence", 0.5)))
            region = analysis.get("region", {}) or {}
            if region and image is not None:
                h, w = image.shape[:2]
                cx = region.get("x", 0) + region.get("w", 0) / 2.0
                cy = region.get("y", 0) + region.get("h", 0) / 2.0
                offset = np.sqrt((cx - w / 2) ** 2 + (cy - h / 2) ** 2) / max(h, w)
                eye_contact = face_confidence * (1.0 - min(1.0, offset * 2.0))
            else:
                eye_contact = face_confidence
            eye_contact_scores.append(eye_contact)

            negative_emotions = sum(
                float(emotions.get(key, 0.0))
                for key in ["angry", "fear", "sad", "disgust"]
            )
            total_emotion = sum(float(v) for v in emotions.values()) or 1.0
            facial_tension_scores.append(negative_emotions / total_emotion)

            is_happy = dominant_emotion == "happy"
            if is_happy and not previous_happy:
                smile_count += 1
            previous_happy = is_happy

        except Exception as exc:
            print(f"[face_analyzer] Warning: failed on {filename} ({exc})")
            continue

    if not timeline:
        print("[face_analyzer] Error: no usable frames after analysis")
        return {}

    emotion_distribution = {
        emotion: value / max(1, len(timeline)) for emotion, value in emotions_sum.items()
    }
    dominant_emotion = max(emotion_distribution, key=emotion_distribution.get)

    micro_expressions: List[Dict[str, Any]] = []
    for i in range(1, len(dominant_emotions) - 1):
        prev_emotion = dominant_emotions[i - 1]
        current_emotion = dominant_emotions[i]
        next_emotion = dominant_emotions[i + 1]
        if prev_emotion == next_emotion and current_emotion != prev_emotion:
            micro_expressions.append(
                {
                    "timestamp": timeline[i]["timestamp"],
                    "emotion": current_emotion,
                    "duration_estimate": "brief",
                }
            )

    emotion_changes = sum(
        1
        for i in range(1, len(dominant_emotions))
        if dominant_emotions[i] != dominant_emotions[i - 1]
    )
    emotion_stability = (
        1.0 - (emotion_changes / max(1, len(dominant_emotions) - 1))
        if len(dominant_emotions) > 1
        else 1.0
    )

    summary = {
        "dominant_emotion": dominant_emotion,
        "emotion_distribution": emotion_distribution,
        "micro_expressions": micro_expressions,
        "eye_contact_score": float(np.mean(eye_contact_scores)) if eye_contact_scores else 0.0,
        "facial_tension_score": float(np.mean(facial_tension_scores))
        if facial_tension_scores
        else 0.0,
        "smile_count": smile_count,
        "emotion_stability": float(emotion_stability),
    }

    print("[face_analyzer] Frame analysis complete")
    return {"emotion_timeline": timeline, "summary": summary}
