"""Live-server API contract checks for the stable E2E lane."""

from __future__ import annotations

import os
import uuid

import httpx
import pytest

SERVER_URL = os.getenv("COUNSELAI_TEST_URL", "http://localhost:8501")


@pytest.fixture(scope="module")
def client() -> httpx.Client:
    with httpx.Client(base_url=SERVER_URL, timeout=10) as c:
        yield c


class TestHealthAndEntryPoints:
    def test_health_endpoint(self, client: httpx.Client):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_index_returns_html(self, client: httpx.Client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")
        assert "CounselAI" in resp.text

    def test_dashboard_returns_html(self, client: httpx.Client):
        resp = client.get("/dashboard")
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")


class TestCaseStudiesAPI:
    def test_case_studies_returns_json(self, client: httpx.Client):
        resp = client.get("/api/case-studies")
        assert resp.status_code == 200
        assert isinstance(resp.json()["case_studies"], list)


class TestDashboardAPIs:
    def test_counsellor_queue_returns_200(self, client: httpx.Client, seeded_dashboard_data):
        resp = client.get("/api/v1/dashboard/counsellor/queue?limit=200")
        assert resp.status_code == 200
        payload = resp.json()
        assert payload["total"] >= 5
        session_ids = {item["session_id"] for item in payload["items"]}
        assert seeded_dashboard_data["sessions"]["review"] in session_ids
        assert seeded_dashboard_data["sessions"]["legacy"] in session_ids

    def test_seeded_review_route_returns_200(self, client: httpx.Client, seeded_dashboard_data):
        review_session_id = seeded_dashboard_data["sessions"]["review"]
        resp = client.get(f"/api/v1/dashboard/counsellor/sessions/{review_session_id}/review")
        assert resp.status_code == 200
        payload = resp.json()
        assert payload["session"]["id"] == review_session_id
        assert payload["profile"] is not None


class TestPostContracts:
    def test_analyze_session_without_data_returns_400(self, client: httpx.Client):
        resp = client.post("/api/analyze-session")
        assert resp.status_code == 400

    def test_removed_rtc_route_is_not_available(self, client: httpx.Client):
        resp = client.post("/api/rtc-connect", content=b"")
        assert resp.status_code in (404, 405, 422)


# ---------------------------------------------------------------------------
# Contract tests below use the session-scoped fixtures from conftest.py
# ---------------------------------------------------------------------------


@pytest.mark.e2e
class TestCaseStudiesContract:
    """Verify shape of each case-study object returned by /api/case-studies."""

    def test_case_study_objects_have_required_fields(self, api_client: httpx.Client):
        resp = api_client.get("/api/case-studies")
        assert resp.status_code == 200
        case_studies = resp.json()["case_studies"]
        assert len(case_studies) > 0, "Expected at least one case study"
        for cs in case_studies:
            assert isinstance(cs.get("id"), str), f"Missing or non-str 'id': {cs}"
            assert isinstance(cs.get("title"), str), f"Missing or non-str 'title': {cs}"
            assert isinstance(cs.get("scenario_text"), str), f"Missing or non-str 'scenario_text': {cs}"
            assert isinstance(cs.get("target_class"), str), f"Missing or non-str 'target_class': {cs}"


@pytest.mark.e2e
class TestQueueContract:
    """Verify the counsellor queue JSON API shape and pagination."""

    QUEUE_URL = "/api/v1/dashboard/counsellor/queue"

    def test_queue_items_have_required_fields(
        self, api_client: httpx.Client, seeded_dashboard_data
    ):
        resp = api_client.get(f"{self.QUEUE_URL}?limit=200")
        assert resp.status_code == 200
        payload = resp.json()
        assert "items" in payload
        assert "total" in payload
        for item in payload["items"]:
            assert "session_id" in item, f"Missing 'session_id': {item}"
            assert "student_name" in item, f"Missing 'student_name': {item}"
            assert "student_grade" in item or "grade" in item, f"Missing grade field: {item}"
            assert "school_name" in item, f"Missing 'school_name': {item}"
            assert "status" in item, f"Missing 'status': {item}"
            assert "started_at" in item, f"Missing 'started_at': {item}"

    def test_queue_limit_param(self, api_client: httpx.Client, seeded_dashboard_data):
        resp = api_client.get(f"{self.QUEUE_URL}?limit=2")
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) <= 2

    def test_queue_offset_param(self, api_client: httpx.Client, seeded_dashboard_data):
        # Use small limit to avoid hitting the 200-cap on large DBs
        full_resp = api_client.get(f"{self.QUEUE_URL}?limit=5")
        full_items = full_resp.json()["items"]
        if len(full_items) < 2:
            pytest.skip("Need at least 2 queue items for offset test")

        offset_resp = api_client.get(f"{self.QUEUE_URL}?limit=5&offset=1")
        offset_items = offset_resp.json()["items"]
        # With offset=1, first item should be what was second before
        assert offset_items[0]["session_id"] == full_items[1]["session_id"]

    def test_seeded_sessions_accessible_via_review(
        self, api_client: httpx.Client, seeded_dashboard_data
    ):
        """Each seeded completed session is accessible via the review endpoint."""
        sessions = seeded_dashboard_data["sessions"]
        for key in ("review", "history_latest", "history_previous", "legacy"):
            resp = api_client.get(
                f"/api/v1/dashboard/counsellor/sessions/{sessions[key]}/review"
            )
            assert resp.status_code == 200, (
                f"Seeded session '{key}' ({sessions[key]}) not accessible via review"
            )


@pytest.mark.e2e
class TestReviewContract:
    """Verify the session review JSON API shape and ordering."""

    def _review_url(self, session_id: str) -> str:
        return f"/api/v1/dashboard/counsellor/sessions/{session_id}/review"

    def test_review_response_shape(
        self, api_client: httpx.Client, seeded_dashboard_data
    ):
        review_id = seeded_dashboard_data["sessions"]["review"]
        resp = api_client.get(self._review_url(review_id))
        assert resp.status_code == 200
        payload = resp.json()

        # Top-level keys
        assert "session" in payload
        assert "profile" in payload
        assert "turns" in payload
        assert "hypotheses" in payload

        # Session sub-object
        session = payload["session"]
        assert session["id"] == review_id
        assert "status" in session

        # Student is a top-level key (sibling of session)
        assert "student" in payload

        # turns and hypotheses are lists
        assert isinstance(payload["turns"], list)
        assert isinstance(payload["hypotheses"], list)

    def test_review_turns_ordered(
        self, api_client: httpx.Client, seeded_dashboard_data
    ):
        review_id = seeded_dashboard_data["sessions"]["review"]
        resp = api_client.get(self._review_url(review_id))
        assert resp.status_code == 200
        turns = resp.json()["turns"]
        if len(turns) >= 2:
            indices = [t["turn_index"] for t in turns]
            assert indices == sorted(indices), f"Turns not ordered: {indices}"

    def test_review_nonexistent_returns_404(self, api_client: httpx.Client):
        fake_id = str(uuid.uuid4())
        resp = api_client.get(self._review_url(fake_id))
        assert resp.status_code == 404


@pytest.mark.e2e
class TestEvidenceContract:
    """Verify the evidence explorer JSON API shape."""

    def _evidence_url(self, session_id: str) -> str:
        return f"/api/v1/dashboard/counsellor/sessions/{session_id}/evidence"

    def test_evidence_returns_observations_and_segments(
        self, api_client: httpx.Client, seeded_dashboard_data
    ):
        review_id = seeded_dashboard_data["sessions"]["review"]
        resp = api_client.get(self._evidence_url(review_id))
        assert resp.status_code == 200
        payload = resp.json()
        assert isinstance(payload.get("observations"), list), "Missing 'observations' list"
        assert isinstance(payload.get("segments"), list), "Missing 'segments' list"
        assert isinstance(payload.get("hypotheses"), list), "Missing 'hypotheses' list"

    def test_evidence_nonexistent_returns_404(self, api_client: httpx.Client):
        fake_id = str(uuid.uuid4())
        resp = api_client.get(self._evidence_url(fake_id))
        assert resp.status_code == 404


@pytest.mark.e2e
class TestAnalyzeContract:
    """Verify error handling for the /api/analyze-session POST endpoint."""

    def test_analyze_missing_transcript_returns_400(self, api_client: httpx.Client):
        resp = api_client.post(
            "/api/analyze-session",
            data={"student_name": "Test Student", "transcript": "[]"},
        )
        assert resp.status_code == 400


@pytest.mark.e2e
class TestDashboardHTMLRoutes:
    """Verify HTML dashboard pages return 404 for nonexistent entities."""

    def test_student_dashboard_nonexistent_returns_404(
        self, api_client: httpx.Client,
    ):
        fake_id = str(uuid.uuid4())
        resp = api_client.get(f"/api/v1/dashboard/students/{fake_id}/insights")
        assert resp.status_code == 404

    def test_school_dashboard_nonexistent_returns_404(
        self, api_client: httpx.Client,
    ):
        fake_id = str(uuid.uuid4())
        resp = api_client.get(f"/api/v1/dashboard/schools/{fake_id}/dashboard")
        assert resp.status_code == 404
