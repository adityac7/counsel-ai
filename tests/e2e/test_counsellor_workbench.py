"""Scenario checks for the counsellor workbench page."""

from __future__ import annotations

from playwright.sync_api import Page, expect


class TestCounsellorWorkbench:
    def test_school_filter_changes_visible_list(
        self,
        page: Page,
        server_url: str,
        seeded_dashboard_data,
    ):
        page.goto(f"{server_url}/api/v1/dashboard/counsellor", wait_until="networkidle")
        page.wait_for_selector("#student-list .student-card", timeout=10_000)

        cards = page.locator("#student-list .student-card")
        initial_count = cards.count()
        assert initial_count >= 3

        page.select_option("#filter-school", seeded_dashboard_data["schools"][1])
        page.wait_for_timeout(300)

        filtered_cards = page.locator("#student-list .student-card")
        filtered_count = filtered_cards.count()
        assert 0 < filtered_count < initial_count
        expect(page.locator("#student-list")).to_contain_text(
            seeded_dashboard_data["names"]["legacy_student"]
        )
        expect(page.locator("#student-list")).not_to_contain_text(
            seeded_dashboard_data["names"]["review_student"]
        )

    def test_grade_filter_and_search_select_student(
        self,
        page: Page,
        server_url: str,
        seeded_dashboard_data,
    ):
        page.goto(f"{server_url}/api/v1/dashboard/counsellor", wait_until="networkidle")
        page.wait_for_selector("#student-list .student-card", timeout=10_000)

        page.select_option("#filter-grade", "10")
        page.fill("#filter-search", seeded_dashboard_data["names"]["history_student"])
        page.wait_for_timeout(300)

        cards = page.locator("#student-list .student-card")
        expect(cards).to_have_count(1)
        expect(cards.first).to_contain_text(seeded_dashboard_data["names"]["history_student"])

        cards.first.click()
        panel = page.locator("#right-panel")
        expect(panel).to_contain_text("Session history (2)")
        expect(panel).to_contain_text("confidence-02")
        expect(panel).to_contain_text("peer-pressure-01")
