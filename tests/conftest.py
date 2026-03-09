"""Shared fixtures for CounselAI test suite."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

from counselai.ingest.artifact_store import ArtifactStore


@pytest.fixture
def tmp_store(tmp_path: Path) -> ArtifactStore:
    """ArtifactStore backed by a temp directory."""
    return ArtifactStore(root=tmp_path / "artifacts")


@pytest.fixture
def session_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def session_id_str(session_id: uuid.UUID) -> str:
    return str(session_id)


@pytest.fixture
def sample_turns_raw() -> list[dict]:
    """Sample canonical turns as raw dicts (turns.jsonl format)."""
    return [
        {
            "turn_index": 0,
            "speaker": "counsellor",
            "text": "Namaste beta, aaj hum peer pressure ke baare mein baat karenge. Tumhare saath kabhi aisa hua?",
            "start_ms": 0,
            "end_ms": 8000,
            "source": "live_transcript",
            "confidence": 0.95,
        },
        {
            "turn_index": 1,
            "speaker": "student",
            "text": "Haan sir, mere friends kabhi kabhi mujhe cheezein karne ke liye force karte hain.",
            "start_ms": 8500,
            "end_ms": 15000,
            "source": "live_transcript",
            "confidence": 0.88,
        },
        {
            "turn_index": 2,
            "speaker": "counsellor",
            "text": "Kya cheezein? Kuch example de sakte ho?",
            "start_ms": 15500,
            "end_ms": 19000,
            "source": "live_transcript",
            "confidence": 0.92,
        },
        {
            "turn_index": 3,
            "speaker": "student",
            "text": "Like bunking classes, ya phir I think maybe smoking... but I don't want to do it.",
            "start_ms": 19500,
            "end_ms": 28000,
            "source": "live_transcript",
            "confidence": 0.85,
        },
        {
            "turn_index": 4,
            "speaker": "counsellor",
            "text": "Aur jab tum mana karte ho, toh kya hota hai?",
            "start_ms": 28500,
            "end_ms": 33000,
            "source": "live_transcript",
            "confidence": 0.93,
        },
        {
            "turn_index": 5,
            "speaker": "student",
            "text": "They make fun of me... call me boring. It hurts but I try to ignore.",
            "start_ms": 33500,
            "end_ms": 42000,
            "source": "live_transcript",
            "confidence": 0.87,
        },
        {
            "turn_index": 6,
            "speaker": "counsellor",
            "text": "Tumhe lagta hai tum sahi kar rahe ho?",
            "start_ms": 42500,
            "end_ms": 46000,
            "source": "live_transcript",
            "confidence": 0.94,
        },
        {
            "turn_index": 7,
            "speaker": "student",
            "text": "I don't know... sometimes I feel like maybe I should just go along. Papa kehte hain ki achhe bacche aisa nahi karte.",
            "start_ms": 46500,
            "end_ms": 58000,
            "source": "live_transcript",
            "confidence": 0.82,
        },
    ]


@pytest.fixture
def sample_content_features(session_id: uuid.UUID) -> dict:
    """Sample content features JSON."""
    return {
        "session_id": str(session_id),
        "topics": [
            {
                "topic_key": "peer_pressure",
                "label": "Peer Pressure",
                "depth": "moderate",
                "turn_indices": [1, 3, 5],
                "start_ms": 8500,
                "end_ms": 42000,
                "confidence": 0.85,
            },
            {
                "topic_key": "self_identity",
                "label": "Self Identity",
                "depth": "surface",
                "turn_indices": [5, 7],
                "start_ms": 33500,
                "end_ms": 58000,
                "confidence": 0.7,
            },
        ],
        "avoidance_events": [],
        "hedging_markers": [
            {
                "turn_index": 3,
                "text": "I think maybe",
                "hedge_type": "qualifier",
                "confidence": 0.8,
            },
            {
                "turn_index": 7,
                "text": "sometimes I feel like maybe",
                "hedge_type": "qualifier",
                "confidence": 0.75,
            },
        ],
        "agency_markers": [
            {
                "turn_index": 3,
                "text": "I don't want to do it",
                "level": "moderate",
                "direction": "self",
                "confidence": 0.8,
            },
        ],
        "code_switch_events": [
            {
                "turn_index": 3,
                "from_language": "hindi",
                "to_language": "english",
                "switch_text": "I think maybe smoking",
                "emotional_context": "discomfort",
                "confidence": 0.75,
            },
            {
                "turn_index": 7,
                "from_language": "english",
                "to_language": "hindi",
                "switch_text": "Papa kehte hain",
                "emotional_context": "deference",
                "confidence": 0.8,
            },
        ],
        "reliability_score": 0.85,
        "overall_depth": "moderate",
        "overall_agency": "low",
        "dominant_language": "hinglish",
    }


@pytest.fixture
def sample_audio_features(session_id: uuid.UUID) -> dict:
    """Sample audio features JSON."""
    return {
        "session_id": str(session_id),
        "turn_features": [
            {
                "turn_index": 1,
                "start_ms": 8500,
                "end_ms": 15000,
                "speech_rate_wpm": 120.0,
                "pitch_mean_hz": 210.0,
                "pitch_std_hz": 25.0,
                "energy_mean_db": -18.0,
                "energy_std_db": 4.0,
                "pause_count": 1,
                "pause_total_ms": 300,
                "dysfluency_count": 0,
                "confidence_score": 0.7,
            },
            {
                "turn_index": 3,
                "start_ms": 19500,
                "end_ms": 28000,
                "speech_rate_wpm": 95.0,
                "pitch_mean_hz": 195.0,
                "pitch_std_hz": 35.0,
                "energy_mean_db": -22.0,
                "energy_std_db": 6.0,
                "pause_count": 2,
                "pause_total_ms": 800,
                "dysfluency_count": 1,
                "confidence_score": 0.45,
            },
            {
                "turn_index": 5,
                "start_ms": 33500,
                "end_ms": 42000,
                "speech_rate_wpm": 110.0,
                "pitch_mean_hz": 200.0,
                "pitch_std_hz": 30.0,
                "energy_mean_db": -20.0,
                "energy_std_db": 5.0,
                "pause_count": 1,
                "pause_total_ms": 400,
                "dysfluency_count": 0,
                "confidence_score": 0.55,
            },
            {
                "turn_index": 7,
                "start_ms": 46500,
                "end_ms": 58000,
                "speech_rate_wpm": 85.0,
                "pitch_mean_hz": 188.0,
                "pitch_std_hz": 40.0,
                "energy_mean_db": -24.0,
                "energy_std_db": 7.0,
                "pause_count": 3,
                "pause_total_ms": 1200,
                "dysfluency_count": 2,
                "confidence_score": 0.35,
            },
        ],
        "pauses": [
            {"start_ms": 12000, "end_ms": 12300, "duration_ms": 300, "turn_index": 1, "is_inter_turn": False},
            {"start_ms": 22000, "end_ms": 22500, "duration_ms": 500, "turn_index": 3, "is_inter_turn": False},
            {"start_ms": 24000, "end_ms": 24300, "duration_ms": 300, "turn_index": 3, "is_inter_turn": False},
        ],
        "dysfluencies": [
            {"turn_index": 3, "start_ms": 21000, "end_ms": 21500, "dysfluency_type": "false_start", "confidence": 0.7},
            {"turn_index": 7, "start_ms": 50000, "end_ms": 50800, "dysfluency_type": "filler", "confidence": 0.65},
            {"turn_index": 7, "start_ms": 54000, "end_ms": 54500, "dysfluency_type": "repetition", "confidence": 0.6},
        ],
        "window_summaries": [],
        "session_summary": {
            "total_duration_ms": 58000,
            "total_speech_ms": 40000,
            "avg_speech_rate_wpm": 102.5,
            "avg_pitch_hz": 198.0,
            "avg_energy_db": -21.0,
            "total_pauses": 7,
            "total_dysfluencies": 3,
        },
        "reliability_score": 0.75,
    }


@pytest.fixture
def sample_video_features(session_id: uuid.UUID) -> dict:
    """Sample video features JSON."""
    return {
        "session_id": str(session_id),
        "frame_count": 120,
        "video_duration_ms": 58000,
        "total_face_visible_pct": 85.0,
        "face_presence": [
            {"start_ms": 0, "end_ms": 58000, "face_detected": True, "face_confidence": 0.9, "face_count": 1},
        ],
        "turn_features": [
            {
                "turn_index": 1,
                "start_ms": 8500,
                "end_ms": 15000,
                "face_visible_pct": 90.0,
                "dominant_gaze": "direct",
                "engagement_estimate": "engaged",
            },
            {
                "turn_index": 3,
                "start_ms": 19500,
                "end_ms": 28000,
                "face_visible_pct": 85.0,
                "dominant_gaze": "downward",
                "engagement_estimate": "passive",
            },
            {
                "turn_index": 5,
                "start_ms": 33500,
                "end_ms": 42000,
                "face_visible_pct": 80.0,
                "dominant_gaze": "averted_left",
                "engagement_estimate": "passive",
            },
            {
                "turn_index": 7,
                "start_ms": 46500,
                "end_ms": 58000,
                "face_visible_pct": 75.0,
                "dominant_gaze": "downward",
                "engagement_estimate": "disengaged",
            },
        ],
        "gaze_observations": [
            {
                "turn_index": 3,
                "start_ms": 21000,
                "end_ms": 25000,
                "direction": "downward",
                "confidence": 0.8,
            },
        ],
        "tension_events": [
            {
                "timestamp_ms": 50000,
                "turn_index": 7,
                "region": "jaw",
                "intensity": 0.7,
                "confidence": 0.6,
            },
        ],
        "movement_events": [
            {
                "turn_index": 5,
                "start_ms": 37000,
                "end_ms": 38000,
                "movement_type": "fidgeting",
                "magnitude": 0.5,
                "confidence": 0.65,
            },
        ],
        "window_summaries": [],
        "gemini_observations": [],
        "reliability_score": 0.7,
    }


def seed_session_artifacts(
    store: ArtifactStore,
    session_id: str,
    turns: list[dict],
    content: dict | None = None,
    audio: dict | None = None,
    video: dict | None = None,
) -> Path:
    """Write sample artifacts to the store for a session. Returns session dir."""
    # Write turns
    store.write_jsonl(session_id, "turns.jsonl", turns)

    # Write session.json
    store.write_json(session_id, "session.json", {
        "session_id": session_id,
        "status": "uploaded",
        "turn_count": len(turns),
    })

    # Write features
    if content:
        features_dir = store.features_dir(session_id)
        (features_dir / "content.json").write_text(
            json.dumps(content, indent=2, default=str), encoding="utf-8",
        )

    if audio:
        features_dir = store.features_dir(session_id)
        (features_dir / "audio.json").write_text(
            json.dumps(audio, indent=2, default=str), encoding="utf-8",
        )

    if video:
        features_dir = store.features_dir(session_id)
        (features_dir / "video.json").write_text(
            json.dumps(video, indent=2, default=str), encoding="utf-8",
        )

    return store.session_dir(session_id)
