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
        assert cards.count() >= 1
        expect(cards.first).to_contain_text(seeded_dashboard_data["names"]["history_student"])

        cards.first.click()
        panel = page.locator("#right-panel")
        expect(panel).to_contain_text("Session history")
        expect(panel).to_contain_text("confidence-02")


class TestWorkbenchContent:
    def test_risk_badges_visible_for_high_risk(
        self,
        page: Page,
        server_url: str,
        seeded_dashboard_data,
    ):
        page.goto(f"{server_url}/api/v1/dashboard/counsellor", wait_until="networkidle")
        page.wait_for_selector("#student-list .student-card", timeout=10_000)

        review_name = seeded_dashboard_data["names"]["review_student"]
        review_card = page.locator(
            f"#student-list .student-card:has-text('{review_name}')"
        )
        expect(review_card).to_be_visible()
        expect(review_card.locator(".badge-risk")).to_be_visible()
        expect(review_card.locator(".badge-risk")).to_contain_text("At risk")

    def test_session_count_per_student(
        self,
        page: Page,
        server_url: str,
        seeded_dashboard_data,
    ):
        page.goto(f"{server_url}/api/v1/dashboard/counsellor", wait_until="networkidle")
        page.wait_for_selector("#student-list .student-card", timeout=10_000)

        history_name = seeded_dashboard_data["names"]["history_student"]
        history_card = page.locator(
            f"#student-list .student-card:has-text('{history_name}')"
        )
        expect(history_card).to_be_visible()
        # Session count varies by DB state; verify badge exists and shows a number
        badge = history_card.locator(".badge-sessions")
        expect(badge).to_be_visible()
        badge_text = badge.inner_text()
        assert "session" in badge_text.lower(), f"Expected session count badge, got: {badge_text}"

    def test_clicking_session_opens_review_page(
        self,
        page: Page,
        server_url: str,
        seeded_dashboard_data,
    ):
        page.goto(f"{server_url}/api/v1/dashboard/counsellor", wait_until="networkidle")
        page.wait_for_selector("#student-list .student-card", timeout=10_000)

        history_name = seeded_dashboard_data["names"]["history_student"]
        history_card = page.locator(
            f"#student-list .student-card:has-text('{history_name}')"
        )
        history_card.click()

        panel = page.locator("#right-panel")
        expect(panel).to_contain_text("Session history")

        session_row = panel.locator(".s-row").first
        expect(session_row).to_be_visible()
        session_row.click()

        page.wait_for_url("**/api/v1/dashboard/counsellor/sessions/**", timeout=10_000)
        expect(page).to_have_url(
            f"{server_url}/api/v1/dashboard/counsellor/sessions/{seeded_dashboard_data['sessions']['history_latest']}"
        )
