"""Real-page smoke coverage for dashboard entry surfaces."""

from __future__ import annotations

from playwright.sync_api import Page, expect


def _load_without_js_or_asset_failures(page: Page, url: str):
    errors: list[str] = []
    asset_failures: list[str] = []

    page.on("pageerror", lambda err: errors.append(str(err)))

    def on_response(response):
        if response.request.resource_type in {"script", "stylesheet"} and response.status >= 400:
            asset_failures.append(f"{response.status} {response.url}")

    page.on("response", on_response)
    response = page.goto(url, wait_until="networkidle")

    assert response is not None
    assert response.status == 200
    assert errors == []
    assert asset_failures == []


class TestDashboardSmoke:
    def test_dashboard_overview_loads(self, page: Page, server_url: str):
        _load_without_js_or_asset_failures(page, f"{server_url}/dashboard")
        expect(page.locator("h1")).to_contain_text("Dashboard")
        expect(page.locator("#sessions-body")).to_be_visible()

    def test_counsellor_workbench_loads(self, page: Page, server_url: str):
        _load_without_js_or_asset_failures(page, f"{server_url}/api/v1/dashboard/counsellor")
        expect(page.locator("h1")).to_contain_text("Counsellor workbench")
        expect(page.locator("#student-list")).to_be_visible()

    def test_seeded_review_page_loads(self, page: Page, server_url: str, seeded_dashboard_data):
        review_session_id = seeded_dashboard_data["sessions"]["review"]
        _load_without_js_or_asset_failures(
            page,
            f"{server_url}/api/v1/dashboard/counsellor/sessions/{review_session_id}",
        )
        assert "Session Review" in page.title()
        expect(page.locator("[data-tab='profile']")).to_be_visible()

    def test_seeded_student_insights_loads(self, page: Page, server_url: str, seeded_dashboard_data):
        student_id = seeded_dashboard_data["students"]["history"]
        _load_without_js_or_asset_failures(
            page,
            f"{server_url}/api/v1/dashboard/students/{student_id}/insights",
        )
        expect(page.locator("h1")).to_contain_text(seeded_dashboard_data["names"]["history_student"])

    def test_seeded_school_dashboard_loads(self, page: Page, server_url: str, seeded_dashboard_data):
        school_id = seeded_dashboard_data["schools"][0]
        _load_without_js_or_asset_failures(
            page,
            f"{server_url}/api/v1/dashboard/schools/{school_id}/dashboard",
        )
        expect(page.locator("h1")).to_contain_text(seeded_dashboard_data["names"]["school_primary"])


class TestDashboardResponsiveSmoke:
    def test_dashboard_mobile_layout_has_no_horizontal_overflow(
        self,
        mobile_page: Page,
        server_url: str,
    ):
        _load_without_js_or_asset_failures(mobile_page, f"{server_url}/dashboard")
        no_overflow = mobile_page.evaluate(
            "() => document.documentElement.scrollWidth <= window.innerWidth"
        )
        assert no_overflow is True
