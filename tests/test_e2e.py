"""Focused HTTP smoke for permanent endpoints."""

from __future__ import annotations

import os

import httpx
import pytest

from tests.e2e.seed_data import ensure_seeded_dashboard_data

SERVER_URL = os.getenv("COUNSELAI_TEST_URL", "http://localhost:8501")


@pytest.fixture(scope="module")
def client() -> httpx.Client:
    with httpx.Client(base_url=SERVER_URL, timeout=10) as c:
        yield c


@pytest.fixture(scope="module")
def seeded_dashboard_data() -> dict[str, object]:
    return ensure_seeded_dashboard_data()


class TestHealth:
    def test_health_endpoint(self, client: httpx.Client) -> None:
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("status") == "ok"


class TestHtmlSurface:
    def test_dashboard_page(self, client: httpx.Client) -> None:
        resp = client.get("/dashboard")
        assert resp.status_code == 200
        assert "Recent sessions" in resp.text

    def test_counsellor_workbench(self, client: httpx.Client) -> None:
        resp = client.get("/api/v1/dashboard/counsellor")
        assert resp.status_code == 200
        assert "Counsellor workbench" in resp.text


class TestDashboardApis:
    def test_counsellor_queue(self, client: httpx.Client) -> None:
        resp = client.get("/api/v1/dashboard/counsellor/queue?limit=1")
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data


class TestSecondaryPages:
    def test_student_insights(
        self,
        client: httpx.Client,
        seeded_dashboard_data: dict[str, object],
    ) -> None:
        student_id = seeded_dashboard_data["students"]["history"]
        resp = client.get(f"/api/v1/dashboard/students/{student_id}/insights")
        assert resp.status_code == 200
        assert "Your personal growth insights" in resp.text

    def test_school_dashboard(
        self,
        client: httpx.Client,
        seeded_dashboard_data: dict[str, object],
    ) -> None:
        school_id = seeded_dashboard_data["schools"][0]
        resp = client.get(f"/api/v1/dashboard/schools/{school_id}/dashboard")
        assert resp.status_code == 200
        assert "School wellness analytics" in resp.text
