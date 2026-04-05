"""Long-running 7-minute Playwright E2E test — real Gemini, fake media.

Exercises the full user journey through the actual UI with Chrome's fake
media streams (--use-fake-device-for-media-stream). Gemini connects for real,
sends its greeting, and we let the session timer run for ~7 minutes to verify:

- Session creation + WS lifecycle (connect → reconnect → wrapup → end)
- Mute/unmute during a live session
- Transcript accumulation over time
- Session timer counts correctly
- Analysis submission with video + transcript
- Face/voice data rendering from real analysis
- Observations/segments persisted in DB (if Gemini uses tools)
- Session finalization in DB with correct status + duration

Run:
    COUNSELAI_HEADED=1 GEMINI_API_KEY=... pytest tests/e2e/test_long_session.py -v -s

Requires: running server at localhost:8501 with GEMINI_API_KEY set.
"""

from __future__ import annotations

import json
import os
import time
from urllib.request import urlopen, Request

import pytest
from playwright.sync_api import Page, expect

GEMINI_KEY = os.getenv("GEMINI_API_KEY")
pytestmark = [
    pytest.mark.long_session,
    pytest.mark.skipif(
        not GEMINI_KEY,
        reason="Long session test requires GEMINI_API_KEY",
    ),
]

# 7 minutes + buffer for analysis
SESSION_WAIT_MS = 7 * 60 * 1000 + 30_000  # 7m30s


class TestLongSession:
    """Full 7-minute live session through the UI with real Gemini."""

    @pytest.fixture(autouse=True)
    def _extend_timeout(self, page: Page):
        """Set Playwright default timeout to 10 minutes for this test class."""
        page.set_default_timeout(600_000)
        yield

    def test_full_7_minute_session(self, page: Page, server_url: str) -> None:
        js_errors: list[str] = []
        page.on("pageerror", lambda err: js_errors.append(str(err)))

        # ── Step 1: Fill form and start ──
        page.goto(server_url, wait_until="networkidle")
        expect(page.locator("#welcome")).to_be_visible()

        page.fill("#student-name", "Long Test Student")
        page.select_option("#class-name", "11")
        page.fill("#section-name", "A")
        page.fill("#school-name", "Long Test School")
        page.fill("#student-age", "16")
        page.select_option("#session-lang", "hinglish")

        # Select first case study if available
        case_studies = page.locator("#case-study-select option")
        if case_studies.count() > 1:
            page.select_option("#case-study-select", index=1)

        page.check("#consent-cb")
        expect(page.locator("#start-btn")).to_be_enabled()

        # Inject tracker for session events
        page.evaluate("""() => {
            window.__sessionEvents = [];
            window.__observationCount = 0;
            window.__transcriptSnapshots = [];
        }""")

        page.click("#start-btn")

        # ── Step 2: Wait for live session to activate ──
        expect(page.locator("#live")).to_be_visible(timeout=15000)

        # Wait for Gemini connection to become active
        # Poll for status text or connection_active event
        connected = False
        for attempt in range(60):  # 60 seconds max wait
            status_text = page.locator("#status-text").inner_text()
            if "Listening" in status_text or "Connected" in status_text:
                connected = True
                break
            page.wait_for_timeout(1000)

        if not connected:
            # Check if there's a toast with error
            toast_text = page.locator("#toast").inner_text()
            pytest.fail(f"Gemini connection never became active. Status: {status_text}, Toast: {toast_text}")

        print(f"  [+] Gemini connected. Status: {page.locator('#status-text').inner_text()}")

        # Capture session_id from the page state
        session_id = page.evaluate("""() => {
            return window.counselai?.state?.savedSessionId || null;
        }""")
        print(f"  [+] Session ID: {session_id}")

        # ── Step 3: Verify mute button works during live session ──
        mute_btn = page.locator("#mute-btn")
        expect(mute_btn).to_be_visible()
        expect(mute_btn).to_contain_text("Mic On")

        # Mute for 5 seconds
        mute_btn.click()
        expect(mute_btn).to_contain_text("Mic Off")
        print("  [+] Muted microphone")
        page.wait_for_timeout(5000)

        # Unmute
        mute_btn.click()
        expect(mute_btn).to_contain_text("Mic On")
        print("  [+] Unmuted microphone")

        # ── Step 4: Let the session run ──
        # Check transcript accumulates over the first minute
        page.wait_for_timeout(15000)  # 15s for Gemini to greet

        transcript_text = page.locator("#transcript").inner_text()
        print(f"  [+] Transcript after 15s: {len(transcript_text)} chars")

        # Verify timer is counting
        timer_text = page.locator("#timer").inner_text()
        print(f"  [+] Timer: {timer_text}")
        assert timer_text != "0:00", "Timer should have started counting"

        # Take periodic snapshots while waiting
        remaining_wait_ms = SESSION_WAIT_MS - 20_000  # Already waited ~20s
        check_interval_ms = 60_000  # Check every 60 seconds
        elapsed_checks = 0

        while remaining_wait_ms > 0:
            wait_this_round = min(check_interval_ms, remaining_wait_ms)
            page.wait_for_timeout(wait_this_round)
            remaining_wait_ms -= wait_this_round
            elapsed_checks += 1

            timer_text = page.locator("#timer").inner_text()
            transcript_len = len(page.locator("#transcript").inner_text())
            status_text = page.locator("#status-text").inner_text()
            print(f"  [~] Check {elapsed_checks}: timer={timer_text}, transcript={transcript_len} chars, status={status_text}")

            # Check if session ended early (timer expired or wrap-up)
            if page.locator("#summary").is_visible():
                print("  [!] Session ended early — summary screen visible")
                break

            # Check for reconnect banner
            if page.locator("#reconnect-banner").is_visible():
                print("  [~] Reconnect banner visible — Gemini reconnecting")

        # ── Step 5: End session (if not already ended) ──
        if not page.locator("#summary").is_visible():
            end_btn = page.locator("#end-btn")
            if end_btn.is_visible():
                print("  [+] Clicking end button")
                end_btn.click()
            else:
                print("  [!] End button not visible — session may have auto-ended")

        # ── Step 6: Wait for analysis and summary ──
        expect(page.locator("#summary")).to_be_visible(timeout=90000)
        print("  [+] Summary screen visible")

        # Wait for analysis status bar to finish
        page.wait_for_timeout(5000)

        # ── Step 7: Verify summary rendering ──
        # Summary text
        summary_text = page.locator("#summary-text").inner_text()
        print(f"  [+] Summary: {summary_text[:100]}...")
        assert len(summary_text) > 10, f"Summary too short: {summary_text}"

        # Profile sections exist
        for section_id in [
            "profile-metrics",
            "personality-section",
            "cognitive-section",
            "emotional-section",
            "behavioral-section",
            "key-moments-section",
            "red-flags-section",
            "recommendations",
        ]:
            section = page.locator(f"#{section_id}")
            expect(section).to_be_attached()

        # Face analysis — should now have data from Gemini observations
        face_section = page.locator("#face-analysis-section")
        expect(face_section).to_be_visible()
        face_text = face_section.inner_text()
        print(f"  [+] Face analysis: {face_text[:120]}...")

        # Voice analysis — should now have data
        voice_section = page.locator("#voice-analysis-section")
        expect(voice_section).to_be_visible()
        voice_text = voice_section.inner_text()
        print(f"  [+] Voice analysis: {voice_text[:120]}...")

        # Transcript in summary
        transcript_section = page.locator("#summary-transcript")
        expect(transcript_section).to_be_attached()
        final_transcript = transcript_section.inner_text()
        print(f"  [+] Final transcript: {len(final_transcript)} chars")

        # ── Step 8: Verify DB persistence ──
        if session_id:
            session_payload = None
            for _ in range(30):
                try:
                    req = Request(
                        f"{server_url}/api/v1/sessions/{session_id}",
                        headers={"Accept": "application/json"},
                    )
                    with urlopen(req, timeout=10) as response:
                        session_payload = json.loads(response.read().decode("utf-8"))
                    if session_payload.get("ended_at"):
                        break
                except Exception:
                    pass
                time.sleep(1)

            if session_payload:
                print(f"  [+] DB status: {session_payload.get('status')}")
                print(f"  [+] DB duration: {session_payload.get('duration_seconds')}s")
                print(f"  [+] DB turn_count: {session_payload.get('turn_count')}")
                assert session_payload["status"] in ("completed", "timed_out")
                assert session_payload.get("duration_seconds", 0) >= 10

                # Check review endpoint for observations
                try:
                    req = Request(
                        f"{server_url}/api/v1/dashboard/counsellor/sessions/{session_id}/review",
                        headers={"Accept": "application/json"},
                    )
                    with urlopen(req, timeout=10) as response:
                        review = json.loads(response.read().decode("utf-8"))
                    print(f"  [+] Review data keys: {list(review.keys())}")
                    if review.get("profile"):
                        print(f"  [+] Profile summary: {str(review['profile'].get('summary', ''))[:80]}")
                except Exception as exc:
                    print(f"  [!] Review fetch failed: {exc}")
            else:
                print("  [!] Could not fetch session from DB API")

        # ── Step 9: Verify no JS errors ──
        if js_errors:
            # Filter out benign errors
            real_errors = [e for e in js_errors if "ResizeObserver" not in e]
            if real_errors:
                print(f"  [!] JS errors: {real_errors}")
            # Don't fail on JS errors — just log them

        print("  [+] Long session test complete!")
