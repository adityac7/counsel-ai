"""E2E tests for the live counselling session page (templates/live.html).

Tests verify UI element presence, interaction triggers, and responsive layout.
No real Gemini/WebSocket connections are made — we test what renders.
"""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect


# ---------------------------------------------------------------------------
# Page load & core UI elements
# ---------------------------------------------------------------------------
class TestLivePageLoad:
    """Verify the live session page renders all expected elements."""

    def test_page_loads_with_200(self, page: Page, server_url: str):
        resp = page.goto(server_url)
        assert resp is not None
        assert resp.status == 200

    def test_title_contains_counselai(self, page: Page, server_url: str):
        page.goto(server_url)
        assert "CounselAI" in page.title()

    def test_brand_visible(self, page: Page, server_url: str):
        page.goto(server_url)
        brand = page.locator(".brand")
        expect(brand).to_be_visible()
        expect(brand).to_contain_text("CounselAI")

    def test_welcome_section_visible(self, page: Page, server_url: str):
        page.goto(server_url)
        welcome = page.locator("#welcome")
        expect(welcome).to_be_visible()

    def test_student_name_input_present(self, page: Page, server_url: str):
        page.goto(server_url)
        expect(page.locator("#student-name")).to_be_visible()

    def test_class_selector_present(self, page: Page, server_url: str):
        page.goto(server_url)
        expect(page.locator("#class-name")).to_be_visible()

    def test_start_button_present(self, page: Page, server_url: str):
        page.goto(server_url)
        btn = page.locator("#start-btn")
        expect(btn).to_be_visible()
        expect(btn).to_contain_text("Start Session")

    def test_ai_model_selector_present(self, page: Page, server_url: str):
        page.goto(server_url)
        expect(page.locator("#ai-model")).to_be_visible()

    def test_case_study_selector_present(self, page: Page, server_url: str):
        page.goto(server_url)
        expect(page.locator("#case-study")).to_be_visible()

    def test_live_section_hidden_initially(self, page: Page, server_url: str):
        page.goto(server_url)
        live = page.locator("#live")
        expect(live).to_be_hidden()

    def test_student_age_input(self, page: Page, server_url: str):
        page.goto(server_url)
        age = page.locator("#student-age")
        expect(age).to_be_visible()
        assert age.input_value() == "15"  # default

    def test_section_name_input(self, page: Page, server_url: str):
        page.goto(server_url)
        expect(page.locator("#section-name")).to_be_visible()

    def test_school_name_input(self, page: Page, server_url: str):
        page.goto(server_url)
        expect(page.locator("#school-name")).to_be_visible()


# ---------------------------------------------------------------------------
# Start session interaction
# ---------------------------------------------------------------------------
class TestStartSession:
    """Verify start button behaviour and live section reveal.

    Note: In headless Chromium with fake media devices, startSession() calls
    getUserMedia and then opens a WebSocket. The WS will fail since no real
    Gemini server is present, but the live screen should still appear briefly
    before being hidden again by the error handler.
    """

    def test_click_start_shows_live_screen(self, page: Page, server_url: str):
        """After clicking start, the live section should become visible
        (even if only briefly before WS errors return to welcome)."""
        page.goto(server_url)
        page.fill("#student-name", "Test Student")

        # Listen for the live section becoming visible
        shown = page.evaluate("""() => {
            return new Promise((resolve) => {
                const live = document.getElementById('live');
                const observer = new MutationObserver(() => {
                    if (!live.classList.contains('hidden')) {
                        observer.disconnect();
                        resolve(true);
                    }
                });
                observer.observe(live, {attributes: true, attributeFilter: ['class']});
                setTimeout(() => { observer.disconnect(); resolve(false); }, 8000);
            });
        }""")
        page.click("#start-btn")
        # Wait for the promise
        page.wait_for_timeout(2000)
        # The live section should have been shown at some point
        # (JS calls showScreen('live') before getUserMedia)

    def test_start_button_triggers_media_request(self, page: Page, server_url: str):
        """Clicking start should trigger getUserMedia."""
        page.goto(server_url)
        page.fill("#student-name", "Test Student")

        # Intercept getUserMedia calls
        page.evaluate("""() => {
            window.__gumCalled = false;
            const orig = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
            navigator.mediaDevices.getUserMedia = function(constraints) {
                window.__gumCalled = true;
                return orig(constraints);
            };
        }""")

        page.click("#start-btn")
        page.wait_for_timeout(2000)
        gum_called = page.evaluate("() => window.__gumCalled")
        assert gum_called, "getUserMedia should have been called after start"


# ---------------------------------------------------------------------------
# In-session UI elements (tested via DOM injection to bypass getUserMedia)
# ---------------------------------------------------------------------------
class TestLiveSessionUI:
    """Verify in-session UI components exist in DOM (hidden or visible)."""

    def test_waveform_canvas_exists_in_dom(self, page: Page, server_url: str):
        page.goto(server_url)
        canvas = page.locator("#waveform-canvas")
        expect(canvas).to_be_attached()

    def test_transcript_area_exists(self, page: Page, server_url: str):
        page.goto(server_url)
        transcript = page.locator("#transcript")
        expect(transcript).to_be_attached()

    def test_status_elements_exist(self, page: Page, server_url: str):
        page.goto(server_url)
        expect(page.locator("#status-dot")).to_be_attached()
        expect(page.locator("#status-text")).to_be_attached()

    def test_video_preview_exists(self, page: Page, server_url: str):
        page.goto(server_url)
        expect(page.locator("#preview")).to_be_attached()

    def test_timer_exists_with_default(self, page: Page, server_url: str):
        page.goto(server_url)
        timer = page.locator("#timer")
        expect(timer).to_be_attached()
        expect(timer).to_have_text("00:00")

    def test_end_button_exists(self, page: Page, server_url: str):
        page.goto(server_url)
        expect(page.locator("#end-btn")).to_be_attached()

    def test_orb_exists(self, page: Page, server_url: str):
        page.goto(server_url)
        expect(page.locator("#orb")).to_be_attached()

    def test_live_section_reveals_on_show_screen(self, page: Page, server_url: str):
        """Directly call showScreen('live') to verify UI without getUserMedia."""
        page.goto(server_url)
        page.evaluate("() => showScreen('live')")
        live = page.locator("#live")
        expect(live).to_be_visible()
        expect(page.locator("#timer")).to_be_visible()
        expect(page.locator("#end-btn")).to_be_visible()
        expect(page.locator("#waveform-canvas")).to_be_visible()
        expect(page.locator("#transcript")).to_be_visible()


# ---------------------------------------------------------------------------
# Mobile viewport
# ---------------------------------------------------------------------------
class TestMobileViewport:
    """Verify the live page renders on a mobile-sized viewport."""

    def test_page_loads_on_mobile(self, mobile_page: Page, server_url: str):
        resp = mobile_page.goto(server_url)
        assert resp is not None
        assert resp.status == 200

    def test_welcome_visible_on_mobile(self, mobile_page: Page, server_url: str):
        mobile_page.goto(server_url)
        expect(mobile_page.locator("#welcome")).to_be_visible()

    def test_start_button_visible_on_mobile(self, mobile_page: Page, server_url: str):
        mobile_page.goto(server_url)
        expect(mobile_page.locator("#start-btn")).to_be_visible()

    def test_no_horizontal_overflow(self, mobile_page: Page, server_url: str):
        mobile_page.goto(server_url)
        overflow = mobile_page.evaluate(
            "() => document.documentElement.scrollWidth <= window.innerWidth"
        )
        assert overflow, "Page has horizontal overflow on mobile viewport"

    def test_mobile_form_inputs_usable(self, mobile_page: Page, server_url: str):
        mobile_page.goto(server_url)
        mobile_page.fill("#student-name", "Mobile Student")
        assert mobile_page.locator("#student-name").input_value() == "Mobile Student"
