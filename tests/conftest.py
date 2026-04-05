"""Shared fixtures for CounselAI test suite."""

from __future__ import annotations

import uuid

import pytest


@pytest.fixture
def session_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def session_id_str(session_id: uuid.UUID) -> str:
    return str(session_id)


@pytest.fixture
def sample_turns_raw() -> list[dict]:
    """Sample canonical turns as raw dicts."""
    return [
        {
            "turn_index": 0,
            "speaker": "counsellor",
            "text": "Namaste beta, aaj hum peer pressure ke baare mein baat karenge.",
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
    ]
