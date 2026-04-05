"""Regression tests for end-session teardown and analysis submission."""

from __future__ import annotations

from playwright.sync_api import Page, expect


_END_SESSION_STUBS = """
(() => {
  window.__analyzeRequest = null;
  window.__wsUrls = [];
  window.__wsMessages = [];
  window.__transcribeCalls = 0;
  window.__simulateZeroVideoChunk = window.__simulateZeroVideoChunk === true;
  window.__activeRecorder = null;

  const originalFetch = window.fetch.bind(window);
  window.fetch = async (input, init = {}) => {
    const url = typeof input === 'string' ? input : input.url;

    if (url.endsWith('/api/case-studies') || url === '/api/case-studies') {
      return new Response(JSON.stringify({
        case_studies: [{
          id: 'cs-1',
          title: 'Mock case',
          target_class: '10',
          scenario_text: 'A student is dealing with peer pressure.'
        }]
      }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' }
      });
    }

    if (url.endsWith('/api/gemini-transcribe') || url === '/api/gemini-transcribe') {
      window.__transcribeCalls += 1;
      return new Response(JSON.stringify({ transcript: 'Final buffered transcript' }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' }
      });
    }

    if (url.endsWith('/api/analyze-session') || url === '/api/analyze-session') {
      const body = init.body;
      window.__analyzeRequest = {
        session_id: body.get('session_id'),
        session_start_time: body.get('session_start_time'),
        session_end_time: body.get('session_end_time'),
        transcript: body.get('transcript'),
        student_name: body.get('student_name'),
        video_size: body.get('video') ? body.get('video').size : null
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
          key_moments: [],
          red_flags: []
        },
        face_data: {},
        voice_data: {}
      }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' }
      });
    }

    return originalFetch(input, init);
  };

  window.MediaRecorder = class FakeMediaRecorder {
    constructor(stream, options = {}) {
      this.stream = stream;
      this.state = 'inactive';
      this.mimeType = options.mimeType || 'video/webm';
      this.onstart = null;
      this.onstop = null;
      this.ondataavailable = null;
      this.onerror = null;
      window.__activeRecorder = this;
    }

    static isTypeSupported() { return true; }

    start() {
      this.state = 'recording';
      if (this.onstart) this.onstart(new Event('start'));
      if (!window.__simulateZeroVideoChunk && this.ondataavailable) {
        setTimeout(() => {
          this.ondataavailable({ data: new Blob(['early-stub-video'], { type: this.mimeType }) });
        }, 30);
      }
    }

    requestData() {
      if (!this.ondataavailable) return;
      const payload = window.__simulateZeroVideoChunk
        ? new Blob([], { type: this.mimeType })
        : new Blob(['stub-video'], { type: this.mimeType });
      this.ondataavailable({ data: payload });
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
      window.__wsUrls.push(url);

      setTimeout(() => {
        this.readyState = 1;
        if (this.onopen) this.onopen(new Event('open'));
      }, 20);

      setTimeout(() => {
        if (this.onmessage) {
          this.onmessage({ data: JSON.stringify({
            type: 'session_started',
            session_id: '11111111-1111-1111-1111-111111111111',
            started_at: '2026-03-17T10:00:00+00:00'
          })});
        }
      }, 40);

      setTimeout(() => {
        if (this.onmessage) this.onmessage({ data: JSON.stringify({ type: 'setup_complete' }) });
      }, 60);

      setTimeout(() => {
        if (this.onmessage) this.onmessage({ data: JSON.stringify({ type: 'connection_active' }) });
      }, 80);

      setTimeout(() => {
        if (this.onmessage) {
          this.onmessage({ data: JSON.stringify({
            serverContent: {
              outputTranscription: { text: 'Thanks for sharing that.' }
            }
          })});
        }
      }, 120);

      setTimeout(() => {
        if (this.onmessage) {
          this.onmessage({ data: JSON.stringify({ serverContent: { turnComplete: true } }) });
        }
      }, 160);
    }

    send(payload) {
      try {
        window.__wsMessages.push(JSON.parse(payload));
      } catch {
        window.__wsMessages.push(payload);
      }
    }

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


def _start_mock_session(page: Page, server_url: str, force_zero_chunks: bool = False) -> list[str]:
  errors: list[str] = []
  init_script = ""
  if force_zero_chunks:
    init_script = "window.__simulateZeroVideoChunk = true;\n"
  init_script += _END_SESSION_STUBS
  page.add_init_script(init_script)
  page.on("pageerror", lambda err: errors.append(str(err)))
  page.goto(server_url)
  page.fill("#student-name", "Regression Student")
  page.select_option("#class-name", "10")
  page.fill("#section-name", "B")
  page.fill("#school-name", "Mock School")
  page.fill("#student-age", "15")
  page.check("#consent-cb")
  page.click("#start-btn")
  page.wait_for_timeout(800)
  expect(page.locator("#live")).to_be_visible()
  return errors


class TestSessionEndReliability:
  def test_end_session_submits_analysis_with_early_session_id(self, page: Page, server_url: str):
    errors = _start_mock_session(page, server_url)

    page.click("#end-btn")
    page.wait_for_function("() => window.__analyzeRequest !== null")

    analyze_request = page.evaluate("() => window.__analyzeRequest")
    assert analyze_request["session_id"] == "11111111-1111-1111-1111-111111111111"
    assert analyze_request["student_name"] == "Regression Student"
    assert "Thanks for sharing that." in analyze_request["transcript"]
    assert analyze_request["session_start_time"]
    assert analyze_request["session_end_time"]
    assert errors == []

  def test_normal_end_does_not_show_connection_lost_toast(self, page: Page, server_url: str):
    _start_mock_session(page, server_url)

    page.click("#end-btn")
    page.wait_for_function("() => window.__analyzeRequest !== null")
    page.wait_for_timeout(250)

    toast_text = page.locator("#toast").text_content() or ""
    assert "Connection lost" not in toast_text
    expect(page.locator("#summary")).to_be_visible()

  def test_empty_recording_path_still_submits_analysis(self, page: Page, server_url: str):
    errors = _start_mock_session(page, server_url, force_zero_chunks=True)

    page.click("#end-btn")
    page.wait_for_function("() => window.__analyzeRequest !== null")

    toast_text = (page.locator("#toast").text_content() or "").strip()
    assert "analysis will continue using transcript data only" in toast_text

    analyze_request = page.evaluate("() => window.__analyzeRequest")
    assert "Thanks for sharing that." in analyze_request["transcript"]
    assert analyze_request["student_name"] == "Regression Student"
    expect(page.locator("#summary")).to_be_visible()
    assert "Mock profile summary" in page.locator("#summary-text").inner_text()
    assert errors == []

  def test_inactive_recorder_reuses_saved_chunks(self, page: Page, server_url: str):
    errors = _start_mock_session(page, server_url)

    page.evaluate("""
      () => {
        if (window.__activeRecorder) window.__activeRecorder.state = 'inactive';
      }
    """)

    page.click("#end-btn")
    page.wait_for_function("() => window.__analyzeRequest !== null")

    analyze_request = page.evaluate("() => window.__analyzeRequest")
    assert analyze_request["video_size"] and analyze_request["video_size"] > 0
    assert "Thanks for sharing that." in analyze_request["transcript"]
    toast_text = (page.locator("#toast").text_content() or "").strip()
    assert "Recording was empty" not in toast_text
    assert errors == []
