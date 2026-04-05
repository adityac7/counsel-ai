"""Scenario checks for the dashboard overview page."""

from __future__ import annotations

from playwright.sync_api import Page, expect


class TestDashboardOverview:
    def test_overview_metrics_and_rows_render(
        self,
        page: Page,
        server_url: str,
        seeded_dashboard_data,
    ):
        page.goto(f"{server_url}/dashboard", wait_until="networkidle")
        page.wait_for_selector("tbody#sessions-body tr.row", timeout=10_000)

        assert page.locator("#st-total").inner_text().strip() not in {"", "0", "—"}
        assert page.locator("#st-students").inner_text().strip() not in {"", "0", "—"}
        assert page.locator("#st-schools").inner_text().strip() not in {"", "0", "—"}
        assert page.locator("#st-avg").inner_text().strip() not in {"", "—"}

        review_row = page.locator(
            f"tr.row[data-id='{seeded_dashboard_data['sessions']['review']}']"
        )
        expect(review_row).to_be_visible()

    def test_overview_row_opens_detail_drawer(
        self,
        page: Page,
        server_url: str,
        seeded_dashboard_data,
    ):
        page.goto(f"{server_url}/dashboard", wait_until="networkidle")
        page.wait_for_selector("tbody#sessions-body tr.row", timeout=10_000)

        page.click(f"tr.row[data-id='{seeded_dashboard_data['sessions']['review']}']")

        detail = page.locator("#session-detail")
        expect(detail).to_be_visible()
        expect(detail).to_contain_text("Session detail")
        expect(detail).to_contain_text(seeded_dashboard_data["names"]["review_student"])
        expect(detail).to_contain_text(seeded_dashboard_data["names"]["session_profile_summary"])
        expect(detail).to_contain_text("Follow up on smoking-related peer triggers.")

    def test_legacy_profile_fallback_renders_in_detail_drawer(
        self,
        page: Page,
        server_url: str,
        seeded_dashboard_data,
    ):
        page.goto(f"{server_url}/dashboard", wait_until="networkidle")
        page.wait_for_selector("tbody#sessions-body tr.row", timeout=10_000)

        page.evaluate(
            """async (sessionId) => {
                await openSession(sessionId);
            }""",
            seeded_dashboard_data["sessions"]["legacy"],
        )

        detail = page.locator("#session-detail")
        expect(detail).to_be_visible()
        expect(detail).to_contain_text("Student feels isolated in the current section.")
        expect(detail).to_contain_text("Check social belonging and teacher support in the next session.")
        expect(detail).to_contain_text("Mentions eating lunch alone most days.")
