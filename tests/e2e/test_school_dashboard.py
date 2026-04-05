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
