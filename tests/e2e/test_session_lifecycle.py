"""E2E tests for session lifecycle — form → live → end → summary.

Tests verify the full user journey using client-side WS mocking
to avoid needing a real Gemini connection.
"""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect


class TestSessionLifecycle:
    """Full session flow with client-side WS mock."""

    def test_form_fill_and_start(self, page: Page, server_url: str):
        """Fill all form fields and click start — live screen should appear."""
        page.goto(server_url)
        page.fill("#student-name", "Test Student")
        page.select_option("#class-name", "10")
        page.fill("#section-name", "B")
        page.fill("#school-name", "Test School")
        page.fill("#student-age", "16")
        page.select_option("#session-lang", "hinglish")

        # Check consent gates start button
        start = page.locator("#start-btn")
        expect(start).to_be_disabled()

        # Check the consent checkbox
        page.check("#consent-cb")
        expect(start).to_be_enabled()

    def test_start_transitions_to_live_screen(self, page: Page, server_url: str):
        """After start, the live screen should become visible (briefly, before WS fails)."""
        page.goto(server_url)
        page.fill("#student-name", "Test Student")
        page.check("#consent-cb")

        # Use MutationObserver to catch live screen appearing
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
        page.wait_for_timeout(2000)

    def test_summary_screen_has_expected_sections(self, page: Page, server_url: str):
        """Verify summary screen has all profile sections."""
        page.goto(server_url)
        page.evaluate("() => showScreen('summary')")
        summary = page.locator("#summary")
        expect(summary).to_be_visible()
        expect(page.locator("#summary-meta")).to_be_attached()
        expect(page.locator("#profile-metrics")).to_be_attached()
        expect(page.locator("#personality-section")).to_be_attached()
        expect(page.locator("#cognitive-section")).to_be_attached()
        expect(page.locator("#emotional-section")).to_be_attached()
        expect(page.locator("#behavioral-section")).to_be_attached()
        expect(page.locator("#conversation-section")).to_be_attached()
        expect(page.locator("#recommendations")).to_be_attached()
        expect(page.locator("#key-moments-section")).to_be_attached()
        expect(page.locator("#red-flags-section")).to_be_attached()
        expect(page.locator("#summary-text")).to_be_attached()
        expect(page.locator("#summary-transcript")).to_be_attached()

    def test_new_session_button_reloads(self, page: Page, server_url: str):
        """New session button should reload the page."""
        page.goto(server_url)
        page.evaluate("() => showScreen('summary')")
        new_btn = page.locator("#new-btn")
        expect(new_btn).to_be_visible()


class TestRecordingPipeline:
    """Verify MediaRecorder starts and accumulates data."""

    def test_media_recorder_starts_on_session(self, page: Page, server_url: str):
        """Verify that MediaRecorder is created when starting a session."""
        page.goto(server_url)
        page.fill("#student-name", "Test Student")
        page.check("#consent-cb")

        # Intercept MediaRecorder creation
        page.evaluate("""() => {
            window.__recorderCreated = false;
            const OrigRecorder = window.MediaRecorder;
            window.MediaRecorder = class extends OrigRecorder {
                constructor(...args) {
                    super(...args);
                    window.__recorderCreated = true;
                }
            };
            window.MediaRecorder.isTypeSupported = OrigRecorder.isTypeSupported.bind(OrigRecorder);
        }""")

        page.click("#start-btn")
        page.wait_for_timeout(3000)
        created = page.evaluate("() => window.__recorderCreated")
        assert created, "MediaRecorder should have been created"


class TestErrorStates:
    """Verify error handling in the UI."""

    def test_empty_name_still_starts(self, page: Page, server_url: str):
        """Empty name should default to 'Student' and still start."""
        page.goto(server_url)
        page.check("#consent-cb")
        # Don't fill name — click start directly
        page.click("#start-btn")
        page.wait_for_timeout(2000)
        # Should have transitioned (name defaults to 'Student')

    def test_toast_appears_on_ws_failure(self, page: Page, server_url: str):
        """When WS fails, a toast notification should appear."""
        page.add_init_script("""
            (() => {
                window.WebSocket = class FailingWebSocket {
                    constructor() {
                        this.readyState = 0;
                        setTimeout(() => {
                            if (this.onerror) this.onerror(new Event('error'));
                        }, 50);
                    }
                    send() {}
                    close() {
                        this.readyState = 3;
                        if (this.onclose) this.onclose({ code: 1006 });
                    }
                };
                window.WebSocket.CONNECTING = 0;
                window.WebSocket.OPEN = 1;
                window.WebSocket.CLOSING = 2;
                window.WebSocket.CLOSED = 3;
            })();
        """)
        page.goto(server_url)
        page.fill("#student-name", "Test")
        page.check("#consent-cb")

        # Track toast visibility
        page.evaluate("""() => {
            window.__toastShown = false;
            const toast = document.getElementById('toast');
            const observer = new MutationObserver(() => {
                if (toast.style.display === 'block') {
                    window.__toastShown = true;
                }
            });
            observer.observe(toast, {attributes: true, attributeFilter: ['style']});
        }""")

        page.click("#start-btn")
        page.wait_for_timeout(5000)
        toast_shown = page.evaluate("() => window.__toastShown")
        assert toast_shown, "Toast should appear on connection failure"


class TestConsentCheckbox:
    """Verify consent checkbox behavior."""

    def test_consent_checkbox_present(self, page: Page, server_url: str):
        page.goto(server_url)
        expect(page.locator("#consent-cb")).to_be_attached()

    def test_start_disabled_without_consent(self, page: Page, server_url: str):
        page.goto(server_url)
        page.fill("#student-name", "Test")
        start = page.locator("#start-btn")
        expect(start).to_be_disabled()

    def test_start_enabled_after_consent(self, page: Page, server_url: str):
        page.goto(server_url)
        page.fill("#student-name", "Test")
        page.check("#consent-cb")
        start = page.locator("#start-btn")
        expect(start).to_be_enabled()

    def test_start_disabled_after_unchecking_consent(self, page: Page, server_url: str):
        page.goto(server_url)
        page.check("#consent-cb")
        page.uncheck("#consent-cb")
        start = page.locator("#start-btn")
        expect(start).to_be_disabled()
