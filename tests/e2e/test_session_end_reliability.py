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


# ---------------------------------------------------------------------------
# Stubs for reconnection / error state tests
# ---------------------------------------------------------------------------

_RECONNECT_STUB = """
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
          id: 'cs-1', title: 'Mock case', target_class: '10',
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
      this.state = 'inactive'; this.mimeType = 'video/webm';
      this.onstart = null; this.ondataavailable = null; this.onstop = null;
    }
    static isTypeSupported() { return true; }
    start() { this.state = 'recording'; if (this.onstart) this.onstart(new Event('start')); }
    requestData() { if (this.ondataavailable) this.ondataavailable({ data: new Blob(['stub'], { type: this.mimeType }) }); }
    stop() { if (this.state === 'inactive') return; this.requestData(); this.state = 'inactive'; if (this.onstop) this.onstop(new Event('stop')); }
  };

  window.WebSocket = class FakeWebSocket {
    constructor(url) {
      this.url = url; this.readyState = 0;
      this.onopen = null; this.onmessage = null;
      this.onclose = null; this.onerror = null;
      window.__wsEvents.push('constructed');

      setTimeout(() => { this.readyState = 1; if (this.onopen) this.onopen(new Event('open')); }, 20);
      setTimeout(() => this._emit({ type: 'session_started', session_id: '44444444-4444-4444-4444-444444444444', started_at: '2026-03-17T10:00:00+00:00' }), 40);
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
    send(payload) { try { window.__wsEvents.push({ send: JSON.parse(payload) }); } catch { window.__wsEvents.push({ send: payload }); } }
    close() { this.readyState = 3; if (this.onclose) this.onclose({ code: 1000, reason: 'stub' }); }
  };
  window.WebSocket.CONNECTING = 0; window.WebSocket.OPEN = 1;
  window.WebSocket.CLOSING = 2; window.WebSocket.CLOSED = 3;
})();
"""


_ERROR_STUB = """
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
          id: 'cs-1', title: 'Mock case', target_class: '10',
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
      this.state = 'inactive'; this.mimeType = 'video/webm';
      this.onstart = null; this.ondataavailable = null; this.onstop = null;
    }
    static isTypeSupported() { return true; }
    start() { this.state = 'recording'; if (this.onstart) this.onstart(new Event('start')); }
    requestData() { if (this.ondataavailable) this.ondataavailable({ data: new Blob(['stub'], { type: this.mimeType }) }); }
    stop() { if (this.state === 'inactive') return; this.requestData(); this.state = 'inactive'; if (this.onstop) this.onstop(new Event('stop')); }
  };

  window.WebSocket = class FakeWebSocket {
    constructor(url) {
      this.url = url; this.readyState = 0;
      this.onopen = null; this.onmessage = null;
      this.onclose = null; this.onerror = null;
      window.__wsEvents.push('constructed');

      setTimeout(() => { this.readyState = 1; if (this.onopen) this.onopen(new Event('open')); }, 20);
      setTimeout(() => this._emit({ type: 'session_started', session_id: '55555555-5555-5555-5555-555555555555', started_at: '2026-03-17T10:00:00+00:00' }), 40);
      setTimeout(() => this._emit({ type: 'setup_complete' }), 60);
      // Emit error instead of connection_active
      setTimeout(() => this._emit({ type: 'error', message: 'Test error' }), 80);
    }
    _emit(payload) {
      window.__wsEvents.push(payload.type || 'payload');
      if (this.onmessage) this.onmessage({ data: JSON.stringify(payload) });
    }
    send(payload) { try { window.__wsEvents.push({ send: JSON.parse(payload) }); } catch { window.__wsEvents.push({ send: payload }); } }
    close() { this.readyState = 3; if (this.onclose) this.onclose({ code: 1000, reason: 'stub' }); }
  };
  window.WebSocket.CONNECTING = 0; window.WebSocket.OPEN = 1;
  window.WebSocket.CLOSING = 2; window.WebSocket.CLOSED = 3;
})();
"""


_INPUT_TRANSCRIPTION_STUB = """
(() => {
  window.__wsEvents = [];
  window.__fetchCalls = [];
  window.__analyzeRequest = null;

  const originalFetch = window.fetch.bind(window);
  window.fetch = async (input, init = {}) => {
    const url = typeof input === 'string' ? input : input.url;
    window.__fetchCalls.push(url);

    if (url.endsWith('/api/case-studies') || url === '/api/case-studies') {
      return new Response(JSON.stringify({
        case_studies: [{
          id: 'cs-1', title: 'Mock case', target_class: '10',
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
      this.state = 'inactive'; this.mimeType = 'video/webm';
      this.onstart = null; this.ondataavailable = null; this.onstop = null;
    }
    static isTypeSupported() { return true; }
    start() { this.state = 'recording'; if (this.onstart) this.onstart(new Event('start')); }
    requestData() { if (this.ondataavailable) this.ondataavailable({ data: new Blob(['stub'], { type: this.mimeType }) }); }
    stop() { if (this.state === 'inactive') return; this.requestData(); this.state = 'inactive'; if (this.onstop) this.onstop(new Event('stop')); }
  };

  window.WebSocket = class FakeWebSocket {
    constructor(url) {
      this.url = url; this.readyState = 0;
      this.onopen = null; this.onmessage = null;
      this.onclose = null; this.onerror = null;
      window.__wsEvents.push('constructed');

      setTimeout(() => { this.readyState = 1; if (this.onopen) this.onopen(new Event('open')); }, 20);
      setTimeout(() => this._emit({ type: 'session_started', session_id: '66666666-6666-6666-6666-666666666666', started_at: '2026-03-17T10:00:00+00:00' }), 40);
      setTimeout(() => this._emit({ type: 'setup_complete' }), 60);
      setTimeout(() => this._emit({ type: 'connection_active' }), 80);
      setTimeout(() => this._emit({ serverContent: { outputTranscription: { text: 'I understand.' } } }), 120);
      setTimeout(() => this._emit({ serverContent: { turnComplete: true } }), 160);
      // Student's last utterance arrives via inputTranscription
      setTimeout(() => this._emit({ serverContent: { inputTranscription: { text: 'I feel stressed about exams.' } } }), 200);
    }
    _emit(payload) {
      window.__wsEvents.push(payload.type || 'payload');
      if (this.onmessage) this.onmessage({ data: JSON.stringify(payload) });
    }
    send(payload) { try { window.__wsEvents.push({ send: JSON.parse(payload) }); } catch { window.__wsEvents.push({ send: payload }); } }
    close() { this.readyState = 3; if (this.onclose) this.onclose({ code: 1000, reason: 'stub' }); }
  };
  window.WebSocket.CONNECTING = 0; window.WebSocket.OPEN = 1;
  window.WebSocket.CLOSING = 2; window.WebSocket.CLOSED = 3;
})();
"""


def _start_reconnect_session(page: Page, server_url: str) -> None:
    page.add_init_script(_RECONNECT_STUB)
    page.goto(server_url, wait_until="networkidle")
    page.fill("#student-name", "Reconnect Student")
    page.select_option("#class-name", "10")
    page.fill("#section-name", "A")
    page.fill("#school-name", "Reconnect School")
    page.fill("#student-age", "15")
    page.check("#consent-cb")
    page.click("#start-btn")
    expect(page.locator("#live")).to_be_visible()
    page.wait_for_function(
        "() => Array.isArray(window.__wsEvents) && window.__wsEvents.includes('connection_active')"
    )


def _start_error_session(page: Page, server_url: str) -> None:
    page.add_init_script(_ERROR_STUB)
    page.goto(server_url, wait_until="networkidle")
    page.fill("#student-name", "Error Student")
    page.select_option("#class-name", "10")
    page.fill("#section-name", "A")
    page.fill("#school-name", "Error School")
    page.fill("#student-age", "15")
    page.check("#consent-cb")
    page.click("#start-btn")
    expect(page.locator("#live")).to_be_visible()
    page.wait_for_function(
        "() => Array.isArray(window.__wsEvents) && window.__wsEvents.includes('error')"
    )


def _start_input_transcription_session(page: Page, server_url: str) -> None:
    page.add_init_script(_INPUT_TRANSCRIPTION_STUB)
    page.goto(server_url, wait_until="networkidle")
    page.fill("#student-name", "Transcript Student")
    page.select_option("#class-name", "10")
    page.fill("#section-name", "A")
    page.fill("#school-name", "Transcript School")
    page.fill("#student-age", "15")
    page.check("#consent-cb")
    page.click("#start-btn")
    expect(page.locator("#live")).to_be_visible()
    page.wait_for_function(
        "() => Array.isArray(window.__wsEvents) && window.__wsEvents.includes('connection_active')"
    )


class TestReconnectionUI:
    def test_reconnect_banner_appears(self, page: Page, server_url: str):
        _start_reconnect_session(page, server_url)
        # Wait for the reconnecting event to fire
        page.wait_for_function(
            "() => Array.isArray(window.__wsEvents) && window.__wsEvents.includes('reconnecting')"
        )
        banner = page.locator("#reconnect-banner")
        expect(banner).to_be_visible()

    def test_wrapup_warning_shows_toast(self, page: Page, server_url: str):
        _start_reconnect_session(page, server_url)
        # Wait for the wrapup_warning event to fire
        page.wait_for_function(
            "() => Array.isArray(window.__wsEvents) && window.__wsEvents.includes('wrapup_warning')"
        )
        # Toast should display time remaining text
        toast = page.locator("#toast")
        page.wait_for_function(
            "() => { const t = document.getElementById('toast'); return t && t.textContent.includes('minute'); }"
        )
        toast_text = toast.text_content() or ""
        assert "minute" in toast_text, f"Expected toast with time remaining, got: {toast_text}"

    def test_connection_state_updates_on_reconnect(self, page: Page, server_url: str):
        _start_reconnect_session(page, server_url)
        # Wait for reconnecting event
        page.wait_for_function(
            "() => Array.isArray(window.__wsEvents) && window.__wsEvents.includes('reconnecting')"
        )
        status_text = page.locator("#status-text").text_content() or ""
        assert "Reconnecting" in status_text, f"Expected 'Reconnecting' in status, got: {status_text}"


class TestErrorStates:
    def test_error_event_shows_error_state(self, page: Page, server_url: str):
        _start_error_session(page, server_url)
        # The error event should be recorded in __wsEvents
        page.wait_for_function(
            "() => Array.isArray(window.__wsEvents) && window.__wsEvents.includes('error')",
            timeout=10000,
        )
        events = page.evaluate("() => window.__wsEvents")
        assert "error" in events, f"Expected 'error' in events, got: {events}"

    def test_last_student_utterance_preserved_on_end(self, page: Page, server_url: str):
        _start_input_transcription_session(page, server_url)
        # Wait for the student inputTranscription to arrive
        page.wait_for_function(
            "() => (document.getElementById('transcript')?.textContent || '').includes('stressed about exams')"
        )
        transcript_text = page.locator("#transcript").text_content() or ""
        assert "stressed about exams" in transcript_text, (
            f"Expected student utterance in transcript before end, got: {transcript_text}"
        )
        # Now end the session and verify the utterance persists in the submitted transcript
        page.click("#end-btn")
        page.wait_for_function("() => window.__analyzeRequest !== null")
        analyze_req = page.evaluate("() => window.__analyzeRequest")
        assert "stressed about exams" in analyze_req["transcript"], (
            f"Expected student utterance in submitted transcript, got: {analyze_req['transcript']}"
        )
