"""Scenario checks for the counsellor session review page."""

from __future__ import annotations

from playwright.sync_api import Page, expect


class TestCounsellorReview:
    def test_profile_tab_renders_seeded_profile(
        self,
        page: Page,
        server_url: str,
        seeded_dashboard_data,
    ):
        session_id = seeded_dashboard_data["sessions"]["review"]
        page.goto(
            f"{server_url}/api/v1/dashboard/counsellor/sessions/{session_id}",
            wait_until="networkidle",
        )

        expect(page.locator("#tab-profile")).to_be_visible()
        expect(page.locator("#tab-profile")).to_contain_text(
            seeded_dashboard_data["names"]["session_profile_summary"]
        )
        expect(page.locator("#tab-profile")).to_contain_text("Red flags")
        expect(page.locator("#tab-profile")).to_contain_text("Follow-ups")

    def test_transcript_tab_shows_text_and_timing(
        self,
        page: Page,
        server_url: str,
        seeded_dashboard_data,
    ):
        session_id = seeded_dashboard_data["sessions"]["review"]
        page.goto(
            f"{server_url}/api/v1/dashboard/counsellor/sessions/{session_id}",
            wait_until="networkidle",
        )

        page.click("[data-tab='transcript']")
        transcript = page.locator("#tab-transcript")
        expect(transcript).to_contain_text("They keep asking me to try smoking once.")
        expect(transcript).to_contain_text("What do you feel in that moment?")
        expect(transcript).to_contain_text("0:00")

    def test_evidence_and_signals_tabs_render_seeded_data(
        self,
        page: Page,
        server_url: str,
        seeded_dashboard_data,
    ):
        session_id = seeded_dashboard_data["sessions"]["review"]
        page.goto(
            f"{server_url}/api/v1/dashboard/counsellor/sessions/{session_id}",
            wait_until="networkidle",
        )

        page.click("[data-tab='evidence']")
        page.wait_for_timeout(400)
        evidence = page.locator("#tab-evidence")
        expect(evidence).to_contain_text("peer_pressure")
        expect(evidence).to_contain_text("risk_language")

        page.click("[data-tab='signals']")
        signals = page.locator("#tab-signals")
        expect(signals).to_contain_text("Topic windows")
        expect(signals).to_contain_text("Hypotheses")
        expect(signals).to_contain_text("Observations")
