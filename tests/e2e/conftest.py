"""Playwright E2E test fixtures for CounselAI.

All tests run against a live server at SERVER_URL (default http://localhost:8501).
No real Gemini/OpenAI calls are made — tests only verify UI rendering,
navigation, and HTTP contract shapes.
"""

from __future__ import annotations

import os

import pytest
from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
SERVER_URL = os.getenv("COUNSELAI_TEST_URL", "http://localhost:8501")

# Viewport presets
DESKTOP_VIEWPORT = {"width": 1280, "height": 720}
MOBILE_VIEWPORT = {"width": 375, "height": 812}


# ---------------------------------------------------------------------------
# Session-scoped browser (one Chromium process for the whole run)
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def _pw():
    with sync_playwright() as pw:
        yield pw


@pytest.fixture(scope="session")
def browser(_pw) -> Browser:
    b = _pw.chromium.launch(
        headless=True,
        args=[
            "--use-fake-device-for-media-stream",
            "--use-fake-ui-for-media-stream",
        ],
    )
    yield b
    b.close()


# ---------------------------------------------------------------------------
# Function-scoped context + page (clean state per test)
# ---------------------------------------------------------------------------
@pytest.fixture()
def context(browser: Browser) -> BrowserContext:
    ctx = browser.new_context(
        viewport=DESKTOP_VIEWPORT,
        ignore_https_errors=True,
        permissions=["microphone", "camera"],
    )
    yield ctx
    ctx.close()


@pytest.fixture()
def page(context: BrowserContext) -> Page:
    p = context.new_page()
    yield p
    p.close()


@pytest.fixture()
def mobile_context(browser: Browser) -> BrowserContext:
    ctx = browser.new_context(
        viewport=MOBILE_VIEWPORT,
        ignore_https_errors=True,
        is_mobile=True,
    )
    yield ctx
    ctx.close()


@pytest.fixture()
def mobile_page(mobile_context: BrowserContext) -> Page:
    p = mobile_context.new_page()
    yield p
    p.close()


@pytest.fixture(scope="session")
def server_url() -> str:
    return SERVER_URL
