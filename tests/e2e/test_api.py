"""Live-server API contract checks for the stable E2E lane."""

from __future__ import annotations

import os

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
