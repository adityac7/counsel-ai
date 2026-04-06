"""Targeted websocket checks for the live session endpoint."""

from __future__ import annotations

import json

from playwright.sync_api import Page, expect


def _ws_base(server_url: str) -> str:
    return server_url.replace("http://", "ws://").replace("https://", "wss://")


class TestWebSocketEndpoint:
    def test_gemini_ws_accepts_upgrade_with_required_params(self, page: Page, server_url: str):
        page.goto(server_url)
        result = page.evaluate(
            """(wsUrl) => {
                return new Promise((resolve) => {
                    let opened = false;
                    const timeout = setTimeout(() => resolve({opened, timed_out: true}), 5000);
                    const query = new URLSearchParams({
                        name: 'Ws Smoke Student',
                        grade: '10',
                        age: '15',
                        section: 'B',
                        school: 'Ws Smoke School',
                        scenario: 'A student is dealing with peer pressure.',
                        lang: 'hinglish',
                    }).toString();

                    const ws = new WebSocket(`${wsUrl}/api/gemini-ws?${query}`);
                    ws.onopen = () => {
                        opened = true;
                    };
                    ws.onmessage = (event) => {
                        clearTimeout(timeout);
                        ws.close();
                        resolve({opened, message: event.data});
                    };
                    ws.onclose = (event) => {
                        clearTimeout(timeout);
                        resolve({opened, closed: true, code: event.code});
                    };
                    ws.onerror = () => {};
                });
            }""",
            _ws_base(server_url),
        )

        assert result["opened"] is True
        if "message" in result:
            payload = json.loads(result["message"])
            assert payload["type"] in {"error", "session_started"}
        else:
            assert result.get("closed") is True

    def test_live_page_ws_url_contains_student_metadata(self, page: Page, server_url: str):
        page.add_init_script(
            """
            (() => {
              window.__wsUrls = [];
              window.WebSocket = class FakeWebSocket {
                constructor(url) {
                  this.url = url;
                  this.readyState = 0;
                  this.onopen = null;
                  this.onmessage = null;
                  this.onclose = null;
                  window.__wsUrls.push(url);
                  setTimeout(() => {
                    this.readyState = 1;
                    if (this.onopen) this.onopen(new Event('open'));
                  }, 10);
                  setTimeout(() => {
                    if (this.onmessage) this.onmessage({ data: JSON.stringify({ type: 'setup_complete' }) });
                  }, 20);
                  setTimeout(() => {
                    if (this.onmessage) this.onmessage({ data: JSON.stringify({ type: 'connection_active' }) });
                  }, 30);
                }
                send() {}
                close() {
                  this.readyState = 3;
                  if (this.onclose) this.onclose({ code: 1000 });
                }
              };
              window.WebSocket.CONNECTING = 0;
              window.WebSocket.OPEN = 1;
              window.WebSocket.CLOSING = 2;
              window.WebSocket.CLOSED = 3;
            })();
            """
        )
        page.goto(server_url, wait_until="networkidle")
        page.fill("#student-name", "Metadata Student")
        page.select_option("#class-name", "11")
        page.fill("#section-name", "C")
        page.fill("#school-name", "Metadata School")
        page.fill("#student-age", "16")
        page.check("#consent-cb")
        page.click("#start-btn")
        page.wait_for_function("() => Array.isArray(window.__wsUrls) && window.__wsUrls.length > 0")

        params = page.evaluate(
            """() => {
                const raw = window.__wsUrls[0];
                const parsed = new URL(raw);
                return {
                    grade: parsed.searchParams.get('grade'),
                    section: parsed.searchParams.get('section'),
                    school: parsed.searchParams.get('school'),
                    age: parsed.searchParams.get('age'),
                };
            }"""
        )
        assert params["grade"] == "11"
        assert params["section"] == "C"
        assert params["school"] == "Metadata School"
        assert params["age"] == "16"

    def test_invalid_ws_path_rejected(self, page: Page, server_url: str):
        page.goto(server_url)
        result = page.evaluate(
            """(wsUrl) => {
                return new Promise((resolve) => {
                    const timeout = setTimeout(() => resolve({opened: false, code: -1}), 3000);
                    const ws = new WebSocket(`${wsUrl}/api/nonexistent-ws`);
                    ws.onopen = () => {
                        clearTimeout(timeout);
                        ws.close();
                        resolve({opened: true, code: 0});
                    };
                    ws.onerror = () => {
                        clearTimeout(timeout);
                        resolve({opened: false, code: -1});
                    };
                    ws.onclose = (event) => {
                        clearTimeout(timeout);
                        resolve({opened: false, code: event.code});
                    };
                });
            }""",
            _ws_base(server_url),
        )
        assert result["opened"] is False


# ---------------------------------------------------------------------------
# Stub shared by lifecycle tests — mirrors _LIVE_SESSION_STUB from
# test_live_session_stubbed.py with __wsEvents tracking.
# ---------------------------------------------------------------------------

_LIFECYCLE_STUB = """
(() => {
  window.__wsEvents = [];
  window.__fetchCalls = [];

  const originalFetch = window.fetch.bind(window);
  window.fetch = async (input, init = {}) => {
    const url = typeof input === 'string' ? input : input.url;
    window.__fetchCalls.push(url);

    if (url.endsWith('/api/case-studies') || url === '/api/case-studies') {
      return new Response(JSON.stringify({
        case_studies: [{
          id: 'cs-1',
          title: 'Mock case',
          target_class: '10',
          scenario_text: 'A student is dealing with peer pressure.'
        }]
      }), { status: 200, headers: { 'Content-Type': 'application/json' } });
    }

    if (url.endsWith('/api/gemini-transcribe') || url === '/api/gemini-transcribe') {
      return new Response(JSON.stringify({ transcript: 'Final buffered transcript' }), {
        status: 200, headers: { 'Content-Type': 'application/json' }
      });
    }

    if (url.endsWith('/api/analyze-session') || url === '/api/analyze-session') {
      const body = init.body;
      window.__analyzeRequest = {
        session_id: body.get('session_id'),
        transcript: body.get('transcript'),
        student_name: body.get('student_name')
      };
      return new Response(JSON.stringify({
        profile: {
          summary: 'Mock profile summary',
          personality_snapshot: { traits: ['reflective'] },
          cognitive_profile: { critical_thinking: 7 },
          emotional_profile: { eq_score: 6 },
          behavioral_insights: { confidence: 5 },
          conversation_analysis: { consistency: 'high' },
          recommendations: ['Plan a follow-up conversation'],
          key_moments: [], red_flags: []
        },
        face_data: {}, voice_data: {}
      }), { status: 200, headers: { 'Content-Type': 'application/json' } });
    }

    return originalFetch(input, init);
  };

  window.MediaRecorder = class FakeMediaRecorder {
    constructor() {
      this.state = 'inactive';
      this.mimeType = 'video/webm';
      this.onstart = null;
      this.ondataavailable = null;
      this.onstop = null;
    }
    static isTypeSupported() { return true; }
    start() {
      this.state = 'recording';
      if (this.onstart) this.onstart(new Event('start'));
    }
    requestData() {
      if (this.ondataavailable) {
        this.ondataavailable({ data: new Blob(['stub'], { type: this.mimeType }) });
      }
    }
    stop() {
      if (this.state === 'inactive') return;
      this.requestData();
      this.state = 'inactive';
      if (this.onstop) this.onstop(new Event('stop'));
    }
  };

  window.WebSocket = class FakeWebSocket {
    constructor(url) {
      this.url = url;
      this.readyState = 0;
      this.onopen = null;
      this.onmessage = null;
      this.onclose = null;
      this.onerror = null;
      window.__wsEvents.push('constructed');

      setTimeout(() => {
        this.readyState = 1;
        if (this.onopen) this.onopen(new Event('open'));
      }, 20);

      setTimeout(() => this._emit({ type: 'session_started', session_id: '33333333-3333-3333-3333-333333333333', started_at: '2026-03-17T10:00:00+00:00' }), 40);
      setTimeout(() => this._emit({ type: 'setup_complete' }), 60);
      setTimeout(() => this._emit({ type: 'connection_active' }), 80);
      setTimeout(() => this._emit({ type: 'reconnecting', attempt: 1, maxAttempts: 3 }), 120);
      setTimeout(() => this._emit({ type: 'wrapup_warning', remaining_seconds: 45 }), 160);
      setTimeout(() => this._emit({ serverContent: { outputTranscription: { text: 'Thanks for sharing that.' } } }), 200);
      setTimeout(() => this._emit({ serverContent: { turnComplete: true } }), 250);
    }

    _emit(payload) {
      window.__wsEvents.push(payload.type || 'payload');
      if (this.onmessage) this.onmessage({ data: JSON.stringify(payload) });
    }

    send(payload) {
      try {
        window.__wsEvents.push({ send: JSON.parse(payload) });
      } catch {
        window.__wsEvents.push({ send: payload });
      }
    }

    close() {
      this.readyState = 3;
      if (this.onclose) this.onclose({ code: 1000, reason: 'stub' });
    }
  };

  window.WebSocket.CONNECTING = 0;
  window.WebSocket.OPEN = 1;
  window.WebSocket.CLOSING = 2;
  window.WebSocket.CLOSED = 3;
})();
"""


def _start_lifecycle_session(page: Page, server_url: str) -> None:
    page.add_init_script(_LIFECYCLE_STUB)
    page.goto(server_url, wait_until="networkidle")
    page.fill("#student-name", "Lifecycle Student")
    page.select_option("#class-name", "10")
    page.fill("#section-name", "A")
    page.fill("#school-name", "Lifecycle School")
    page.fill("#student-age", "15")
    page.check("#consent-cb")
    page.click("#start-btn")
    expect(page.locator("#live")).to_be_visible()
    page.wait_for_function(
        "() => Array.isArray(window.__wsEvents) && window.__wsEvents.includes('connection_active')"
    )


class TestWebSocketLifecycle:
    def test_session_events_arrive_in_order(self, page: Page, server_url: str):
        _start_lifecycle_session(page, server_url)
        # Wait for connection_active which is the last of the early lifecycle events
        events = page.evaluate("() => window.__wsEvents")
        ordered = ["constructed", "session_started", "setup_complete", "connection_active"]
        indices = [events.index(e) for e in ordered]
        assert indices == sorted(indices), f"Events out of order: {events}"

    def test_transcript_shows_counsellor_text(self, page: Page, server_url: str):
        _start_lifecycle_session(page, server_url)
        page.wait_for_function(
            "() => (document.getElementById('transcript')?.textContent || '').includes('Thanks for sharing that.')"
        )
        transcript = page.locator("#transcript")
        expect(transcript).to_contain_text("Thanks for sharing that.")

    def test_session_id_captured(self, page: Page, server_url: str):
        _start_lifecycle_session(page, server_url)
        # Verify session_started event was received via __wsEvents
        has_started = page.wait_for_function(
            "() => window.__wsEvents && window.__wsEvents.includes('session_started')",
            timeout=10000,
        ).json_value()
        assert has_started

    def test_timer_starts_on_session(self, page: Page, server_url: str):
        _start_lifecycle_session(page, server_url)
        timer = page.locator("#timer")
        expect(timer).to_be_visible()
        # Wait briefly for the timer to tick at least once
        page.wait_for_timeout(1200)
        timer_text = timer.text_content() or ""
        assert timer_text != "", "Timer should display elapsed time"
        # Timer should have advanced past 00:00
        assert timer_text != "00:00", f"Timer should have ticked, got: {timer_text}"

    def test_end_session_sends_handshake(self, page: Page, server_url: str):
        _start_lifecycle_session(page, server_url)
        # Wait for transcript so session is fully active
        page.wait_for_function(
            "() => (document.getElementById('transcript')?.textContent || '').includes('Thanks for sharing that.')"
        )
        page.click("#end-btn")
        # Wait for the end_session message to be sent via WS
        page.wait_for_function(
            "() => window.__wsEvents.some(e => typeof e === 'object' && e.send && e.send.type === 'end_session')"
        )
        events = page.evaluate("() => window.__wsEvents")
        end_msgs = [e for e in events if isinstance(e, dict) and "send" in e and isinstance(e["send"], dict) and e["send"].get("type") == "end_session"]
        assert len(end_msgs) >= 1, f"Expected end_session send event, got: {events}"
