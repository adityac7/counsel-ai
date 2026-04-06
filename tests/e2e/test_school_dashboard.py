"""Scenario checks for the school analytics page."""

from __future__ import annotations

from playwright.sync_api import Page, expect


class TestSchoolDashboard:
    def test_seeded_school_dashboard_renders_aggregate_sections(
        self,
        page: Page,
        server_url: str,
        seeded_dashboard_data,
    ):
        school_id = seeded_dashboard_data["schools"][0]
        page.goto(
            f"{server_url}/api/v1/dashboard/schools/{school_id}/dashboard",
            wait_until="networkidle",
        )

        expect(page.locator(".page-header h1")).to_contain_text(
            seeded_dashboard_data["names"]["school_primary"]
        )
        expect(page.locator("text=Grade distribution")).to_be_visible()
        expect(page.locator("text=Red flag overview")).to_be_visible()
        expect(page.locator("text=Top discussion topics")).to_be_visible()
        expect(page.locator("text=Construct analysis")).to_be_visible()
        expect(page.locator("text=Section breakdown")).to_be_visible()
        expect(page.locator("text=Processing pipeline")).to_be_visible()

    def test_school_dashboard_renders_tables_and_chart(
        self,
        page: Page,
        server_url: str,
        seeded_dashboard_data,
    ):
        school_id = seeded_dashboard_data["schools"][0]
        page.goto(
            f"{server_url}/api/v1/dashboard/schools/{school_id}/dashboard",
            wait_until="networkidle",
        )

        expect(page.locator("#trendChart")).to_be_visible()
        expect(page.locator("text=Peer Pressure").first).to_be_visible()
        expect(page.locator(".table-wrap table")).to_have_count(2)


class TestSchoolDashboardPrivacy:
    def test_no_individual_student_names(
        self,
        page: Page,
        server_url: str,
        seeded_dashboard_data,
    ):
        school_id = seeded_dashboard_data["schools"][0]
        page.goto(
            f"{server_url}/api/v1/dashboard/schools/{school_id}/dashboard",
            wait_until="networkidle",
        )

        body_text = page.locator("body").inner_text()
        for key in ("history_student", "review_student", "legacy_student"):
            full_name = seeded_dashboard_data["names"].get(key, "")
            if full_name:
                assert full_name not in body_text, (
                    f"Individual student name '{full_name}' should not appear on school dashboard"
                )


class TestSchoolDashboardEdgeCases:
    def test_second_school_has_different_data(
        self,
        page: Page,
        server_url: str,
        seeded_dashboard_data,
    ):
        school_id = seeded_dashboard_data["schools"][1]
        page.goto(
            f"{server_url}/api/v1/dashboard/schools/{school_id}/dashboard",
            wait_until="networkidle",
        )

        primary_name = seeded_dashboard_data["names"]["school_primary"]
        secondary_name = seeded_dashboard_data["names"]["school_secondary"]
        expect(page.locator(".page-header h1")).to_contain_text(secondary_name)
        body_text = page.locator("body").inner_text()
        assert primary_name not in body_text, (
            "Primary school name should not appear on the secondary school dashboard"
        )

    def test_stats_are_numeric(
        self,
        page: Page,
        server_url: str,
        seeded_dashboard_data,
    ):
        school_id = seeded_dashboard_data["schools"][0]
        page.goto(
            f"{server_url}/api/v1/dashboard/schools/{school_id}/dashboard",
            wait_until="networkidle",
        )

        stat_cards = page.locator(".stats-row .stat-card .val")
        count = stat_cards.count()
        assert count > 0, "Expected at least one stat card on school dashboard"
        for i in range(count):
            text = stat_cards.nth(i).inner_text().strip()
            assert text != "", f"Stat card {i} is empty"
            assert "NaN" not in text, f"Stat card {i} contains NaN"
