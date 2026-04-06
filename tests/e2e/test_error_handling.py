"""Error handling and edge case tests across CounselAI."""
from __future__ import annotations

import os
import uuid

import httpx
import pytest
from playwright.sync_api import Page, expect

SERVER_URL = os.getenv("COUNSELAI_TEST_URL", "http://localhost:8501")


@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=SERVER_URL, timeout=10) as c:
        yield c


class TestInvalidUUIDs:
    def test_invalid_uuid_session_review_404(self, client: httpx.Client):
        r = client.get(f"/api/v1/dashboard/counsellor/sessions/{uuid.uuid4()}/review")
        assert r.status_code == 404

    def test_invalid_uuid_session_evidence_404(self, client: httpx.Client):
        r = client.get(f"/api/v1/dashboard/counsellor/sessions/{uuid.uuid4()}/evidence")
        assert r.status_code == 404

    def test_invalid_uuid_student_insights_404(self, client: httpx.Client):
        r = client.get(f"/api/v1/dashboard/students/{uuid.uuid4()}/insights")
        assert r.status_code in (404, 500)

    def test_invalid_uuid_school_dashboard_404(self, client: httpx.Client):
        r = client.get(f"/api/v1/dashboard/schools/{uuid.uuid4()}/dashboard")
        assert r.status_code in (404, 500)


class TestStaticAssets:
    def test_dashboard_css_loads(self, client: httpx.Client):
        r = client.get("/static/dashboard.css")
        assert r.status_code == 200

    def test_live_css_loads(self, client: httpx.Client):
        r = client.get("/static/live/live.css")
        assert r.status_code == 200

    def test_live_js_modules_load(self, client: httpx.Client):
        r = client.get("/static/live/app.js")
        assert r.status_code == 200


class TestNoJSErrors:
    def test_dashboard_no_console_errors(self, page: Page, server_url: str):
        errors: list[str] = []
        page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)
        page.goto(f"{server_url}/dashboard", wait_until="networkidle")
        filtered = [e for e in errors if "favicon" not in e.lower()]
        assert filtered == [], f"Console errors on /dashboard: {filtered}"

    def test_live_page_no_console_errors(self, page: Page, server_url: str):
        errors: list[str] = []
        page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)
        page.goto(f"{server_url}/", wait_until="networkidle")
        filtered = [e for e in errors if "favicon" not in e.lower()]
        assert filtered == [], f"Console errors on /: {filtered}"
