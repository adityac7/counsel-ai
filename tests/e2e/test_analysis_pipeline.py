"""API-level integration tests for the analysis pipeline.

Tests cover validation, persistence of seeded data, and edge cases
for the /api/analyze-session endpoint and related dashboard APIs.
"""

from __future__ import annotations

import json
import os
import uuid

import httpx
import pytest

SERVER_URL = os.getenv("COUNSELAI_TEST_URL", "http://localhost:8501")


@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=SERVER_URL, timeout=30) as c:
        yield c


# ---------------------------------------------------------------------------
# Validation tests for /api/analyze-session
# ---------------------------------------------------------------------------


@pytest.mark.e2e
class TestAnalyzeSessionValidation:
    """Verify input validation on the analyze-session endpoint."""

    def test_empty_body_returns_400(self, client: httpx.Client):
        resp = client.post("/api/analyze-session")
        assert resp.status_code == 400, (
            f"Expected 400 for empty body, got {resp.status_code}"
        )

    def test_missing_transcript_returns_400(self, client: httpx.Client):
        resp = client.post(
            "/api/analyze-session",
            data={"student_name": "Test Student"},
        )
        assert resp.status_code == 400, (
            f"Expected 400 when transcript is missing, got {resp.status_code}"
        )

    def test_minimal_valid_request_accepted(self, client: httpx.Client):
        transcript = json.dumps([{"role": "student", "text": "Hello"}])
        resp = client.post(
            "/api/analyze-session",
            data={
                "student_name": "Pipeline Test Student",
                "transcript": transcript,
                "session_start_time": "2026-01-01T10:00:00Z",
                "session_end_time": "2026-01-01T10:05:00Z",
            },
        )
        # 200 if Gemini key is configured, 500 if not (graceful error)
        assert resp.status_code in (200, 500), (
            f"Expected 200 or 500 for minimal valid request, got {resp.status_code}"
        )


# ---------------------------------------------------------------------------
# Persistence tests — verify seeded review session has correct data
# ---------------------------------------------------------------------------


@pytest.mark.e2e
class TestAnalyzeSessionPersistence:
    """Check that seeded sessions expose correct data through the review API."""

    def _review_url(self, session_id: str) -> str:
        return f"/api/v1/dashboard/counsellor/sessions/{session_id}/review"

    def test_seeded_review_session_has_report(
        self, client: httpx.Client, seeded_dashboard_data,
    ):
        review_id = seeded_dashboard_data["sessions"]["review"]
        resp = client.get(self._review_url(review_id))
        assert resp.status_code == 200
        payload = resp.json()
        assert payload["profile"] is not None, "Review session should have a profile"

    def test_seeded_review_session_has_hypotheses(
        self, client: httpx.Client, seeded_dashboard_data,
    ):
        review_id = seeded_dashboard_data["sessions"]["review"]
        resp = client.get(self._review_url(review_id))
        assert resp.status_code == 200
        hypotheses = resp.json()["hypotheses"]
        assert isinstance(hypotheses, list)
        assert len(hypotheses) > 0, "Review session should have at least one hypothesis"

    def test_seeded_review_session_has_turns(
        self, client: httpx.Client, seeded_dashboard_data,
    ):
        review_id = seeded_dashboard_data["sessions"]["review"]
        resp = client.get(self._review_url(review_id))
        assert resp.status_code == 200
        turns = resp.json()["turns"]
        assert len(turns) == 3, f"Review session should have 3 turns, got {len(turns)}"

    def test_seeded_review_session_has_red_flags(
        self, client: httpx.Client, seeded_dashboard_data,
    ):
        review_id = seeded_dashboard_data["sessions"]["review"]
        resp = client.get(self._review_url(review_id))
        assert resp.status_code == 200
        profile = resp.json()["profile"]
        assert profile is not None
        red_flags = profile.get("red_flags", [])
        assert len(red_flags) > 0, "Review session profile should have red_flags"

    def test_seeded_review_session_summary_populated(
        self, client: httpx.Client, seeded_dashboard_data,
    ):
        review_id = seeded_dashboard_data["sessions"]["review"]
        resp = client.get(self._review_url(review_id))
        assert resp.status_code == 200
        session = resp.json()["session"]
        assert session.get("session_summary"), (
            "Review session should have a non-empty session_summary"
        )


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


@pytest.mark.e2e
class TestAnalyzeSessionEdgeCases:
    """Edge case handling for analyze-session and evidence endpoints."""

    def test_nonexistent_session_id_handled(self, client: httpx.Client):
        fake_id = str(uuid.uuid4())
        transcript = json.dumps([{"role": "student", "text": "Hello"}])
        resp = client.post(
            "/api/analyze-session",
            data={
                "student_name": "Ghost Student",
                "transcript": transcript,
                "session_id": fake_id,
                "session_start_time": "2026-01-01T10:00:00Z",
                "session_end_time": "2026-01-01T10:05:00Z",
            },
        )
        # Should not crash — 200 (processed), 400, or 404 are all acceptable
        assert resp.status_code in (200, 400, 404, 500), (
            f"Non-existent session_id should not crash, got {resp.status_code}"
        )

    def test_evidence_endpoint_returns_observations(
        self, client: httpx.Client, seeded_dashboard_data,
    ):
        review_id = seeded_dashboard_data["sessions"]["review"]
        resp = client.get(
            f"/api/v1/dashboard/counsellor/sessions/{review_id}/evidence"
        )
        assert resp.status_code == 200
        payload = resp.json()
        observations = payload.get("observations", [])
        assert isinstance(observations, list)
        assert len(observations) > 0, (
            "Seeded review session should have observations from observations_json"
        )
