"""Smoke coverage for the live session entry page."""

from __future__ import annotations

from playwright.sync_api import Page, expect


def _assert_page_has_no_errors(page: Page, url: str):
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


class TestLivePageSmoke:
    def test_live_page_loads(self, page: Page, server_url: str):
        _assert_page_has_no_errors(page, server_url)
        expect(page.locator(".brand")).to_contain_text("CounselAI")
        expect(page.locator("#welcome")).to_be_visible()

    def test_consent_gates_start_button(self, page: Page, server_url: str):
        page.goto(server_url, wait_until="networkidle")
        start_btn = page.locator("#start-btn")
        expect(start_btn).to_be_disabled()
        page.check("#consent-cb")
        expect(start_btn).to_be_enabled()

    def test_case_studies_populate_dropdown(self, page: Page, server_url: str):
        page.goto(server_url, wait_until="networkidle")
        options = page.locator("#case-study option")
        assert options.count() >= 1
        assert options.first.text_content()

    def test_case_study_preview_updates(self, page: Page, server_url: str):
        page.goto(server_url, wait_until="networkidle")
        options = page.locator("#case-study option")
        if options.count() < 2:
            expect(page.locator("#case-study-text")).not_to_be_empty()
            return
        page.select_option("#case-study", index=1)
        expect(page.locator("#case-study-text")).not_to_be_empty()

    def test_live_dom_sections_are_attached(self, page: Page, server_url: str):
        page.goto(server_url, wait_until="networkidle")
        expect(page.locator("#live")).to_be_hidden()
        expect(page.locator("#summary")).to_be_hidden()
        expect(page.locator("#timer")).to_be_attached()
        expect(page.locator("#transcript")).to_be_attached()
        expect(page.locator("#end-btn")).to_be_attached()


class TestLivePageResponsive:
    def test_mobile_layout_has_no_horizontal_overflow(self, mobile_page: Page, server_url: str):
        _assert_page_has_no_errors(mobile_page, server_url)
        no_overflow = mobile_page.evaluate(
            "() => document.documentElement.scrollWidth <= window.innerWidth"
        )
        assert no_overflow is True

    def test_mobile_start_button_remains_visible(self, mobile_page: Page, server_url: str):
        mobile_page.goto(server_url, wait_until="networkidle")
        expect(mobile_page.locator("#start-btn")).to_be_visible()
