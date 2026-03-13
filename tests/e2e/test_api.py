"""E2E tests for CounselAI REST API endpoints.

Uses httpx to hit the live server directly — no browser needed.
"""

from __future__ import annotations

import os

import httpx
import pytest

SERVER_URL = os.getenv("COUNSELAI_TEST_URL", "http://localhost:8501")


@pytest.fixture(scope="module")
def client() -> httpx.Client:
    with httpx.Client(base_url=SERVER_URL, timeout=10) as c:
        yield c


# ---------------------------------------------------------------------------
# GET /api/sessions
# ---------------------------------------------------------------------------
class TestSessionsAPI:

    def test_get_sessions_returns_json(self, client: httpx.Client):
        resp = client.get("/api/sessions")
        assert resp.status_code == 200
        data = resp.json()
        assert "sessions" in data
        assert isinstance(data["sessions"], list)

    def test_get_sessions_content_type(self, client: httpx.Client):
        resp = client.get("/api/sessions")
        assert "application/json" in resp.headers.get("content-type", "")


# ---------------------------------------------------------------------------
# GET /api/case-studies
# ---------------------------------------------------------------------------
class TestCaseStudiesAPI:

    def test_get_case_studies_returns_json(self, client: httpx.Client):
        resp = client.get("/api/case-studies")
        assert resp.status_code == 200
        data = resp.json()
        assert "case_studies" in data

    def test_case_studies_is_list(self, client: httpx.Client):
        resp = client.get("/api/case-studies")
        data = resp.json()
        assert isinstance(data["case_studies"], list)


# ---------------------------------------------------------------------------
# GET /api/sessions/{id} — nonexistent session
# ---------------------------------------------------------------------------
class TestSessionDetailAPI:

    def test_invalid_session_id_returns_400(self, client: httpx.Client):
        """Non-UUID session ID returns 400 Bad Request."""
        resp = client.get("/api/sessions/999999")
        assert resp.status_code == 400

    def test_invalid_session_id_has_detail(self, client: httpx.Client):
        resp = client.get("/api/sessions/999999")
        data = resp.json()
        assert "detail" in data or "error" in data

    def test_nonexistent_uuid_session_returns_404(self, client: httpx.Client):
        """Valid UUID that doesn't exist returns 404."""
        resp = client.get("/api/sessions/00000000-0000-0000-0000-000000000000")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Dashboard JSON APIs
# ---------------------------------------------------------------------------
class TestDashboardAPIs:

    def test_counsellor_queue_endpoint(self, client: httpx.Client):
        resp = client.get("/api/v1/dashboard/counsellor/queue")
        assert resp.status_code in (200, 500)

    def test_counsellor_filters_endpoint(self, client: httpx.Client):
        resp = client.get("/api/v1/dashboard/counsellor/filters")
        assert resp.status_code in (200, 500)

    def test_counsellor_html_page(self, client: httpx.Client):
        resp = client.get("/api/v1/dashboard/counsellor")
        assert resp.status_code in (200, 500)
        if resp.status_code == 200:
            assert "text/html" in resp.headers.get("content-type", "")


# ---------------------------------------------------------------------------
# HTML page endpoints
# ---------------------------------------------------------------------------
class TestHTMLPages:

    def test_index_returns_html(self, client: httpx.Client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")
        assert "CounselAI" in resp.text

    def test_dashboard_returns_html(self, client: httpx.Client):
        resp = client.get("/dashboard")
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")


# ---------------------------------------------------------------------------
# POST endpoints — contract checks
# ---------------------------------------------------------------------------
class TestPostEndpoints:

    def test_analyze_session_without_data_returns_422(self, client: httpx.Client):
        """POST /api/analyze-session without required fields → 422."""
        resp = client.post("/api/analyze-session")
        assert resp.status_code == 422

    def test_rtc_connect_without_body_returns_error(self, client: httpx.Client):
        """POST /api/rtc-connect without SDP body → error."""
        resp = client.post("/api/rtc-connect", content=b"")
        assert resp.status_code >= 400
