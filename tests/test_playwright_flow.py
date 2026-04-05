"""Minimal Playwright sanity checks for the live session UI."""

from __future__ import annotations

import os

import pytest
from playwright.sync_api import Browser, Page, expect, sync_playwright

SERVER_URL = os.getenv("COUNSELAI_TEST_URL", "http://localhost:8501")


@pytest.fixture(scope="session")
def server_url() -> str:
    return SERVER_URL


@pytest.fixture(scope="module")
def browser() -> Browser:
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            chromium_sandbox=False,
            args=["--no-sandbox", "--disable-setuid-sandbox"],
        )
        yield browser
        browser.close()


@pytest.fixture
def page(browser: Browser) -> Page:
    context = browser.new_context(ignore_https_errors=True)
    page = context.new_page()
    yield page
    context.close()


class TestLiveEntryForm:
    def test_start_button_requires_consent(self, page: Page, server_url: str) -> None:
        page.goto(server_url)
        start_btn = page.locator("#start-btn")
        assert start_btn.is_enabled() is False
        page.fill("#student-name", "Sanity Student")
        page.check("#consent-cb")
        expect(start_btn).to_be_enabled()
        page.uncheck("#consent-cb")
        expect(start_btn).to_be_disabled()


class TestSummaryScreen:
    def test_summary_sections_render(self, page: Page, server_url: str) -> None:
        page.goto(server_url)
        page.evaluate(
            "() => {"
            "document.getElementById('student-name').value = 'Injected';"
            "window.transcriptEntries = [{ role: 'student', text: 'Hello' }, { role: 'counsellor', text: 'Hi' }];"
            "showScreen('summary');"
            "}"
        )
        expect(page.locator("#summary")).to_be_visible()
        expect(page.locator("#profile-metrics")).to_be_attached()
        expect(page.locator("#personality-section")).to_be_attached()
        expect(page.locator("#recommendations")).to_be_attached()
        expect(page.locator("#summary-transcript")).to_be_attached()
