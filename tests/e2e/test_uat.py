"""Headed-only manual UAT checks.

These tests are intentionally excluded from the stable regression lane.
They keep a small visual-audit path for humans without polluting default E2E runs.
"""

from __future__ import annotations

import os

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.uat

HEADED = os.getenv("COUNSELAI_HEADED", "0") == "1"


@pytest.mark.skipif(not HEADED, reason="Manual UAT is intended for headed visual runs.")
class TestManualUAT:
    def test_live_page_visual_audit(self, page: Page, server_url: str):
        page.goto(server_url, wait_until="networkidle")
        expect(page.locator("#welcome")).to_be_visible()
        expect(page.locator(".topbar")).to_be_visible()

    def test_dashboard_visual_audit(self, page: Page, server_url: str, seeded_dashboard_data):
        page.goto(f"{server_url}/dashboard", wait_until="networkidle")
        expect(page.locator("h1")).to_contain_text("Sessions Dashboard")
        page.click(f"tr[data-id='{seeded_dashboard_data['sessions']['review']}']")
        expect(page.locator("#session-detail")).to_contain_text("Session detail")

    def test_review_visual_audit(self, page: Page, server_url: str, seeded_dashboard_data):
        page.goto(
            f"{server_url}/api/v1/dashboard/counsellor/sessions/{seeded_dashboard_data['sessions']['review']}",
            wait_until="networkidle",
        )
        expect(page.locator("[data-tab='profile']")).to_be_visible()
        page.click("[data-tab='evidence']")
        expect(page.locator("#tab-evidence")).to_be_visible()
