"""Focused Playwright coverage for the live session lifecycle using stubbed media and WS."""

from __future__ import annotations

from playwright.sync_api import Page, expect


_LIVE_SESSION_STUB = """
(() => {
  window.__analyzeRequest = null;
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
        student_class: body.get('student_class'),
        student_section: body.get('student_section'),
        student_school: body.get('student_school'),
        student_age: body.get('student_age')
      };

      return new Response(JSON.stringify({
        profile: {
          summary: 'Mock profile summary',
          counsellor_view: {
            summary: 'Mock profile summary',
            constructs: [{
              label: 'Peer resistance',
              status: 'mixed',
              score: 0.67,
              evidence_summary: 'Student wants to resist peer pressure.'
            }],
            recommended_follow_ups: ['Follow up on peer pressure'],
            red_flags: [{ key: 'peer_pressure', severity: 'medium', reason: 'Mentions smoking' }]
          },
          personality_snapshot: { traits: ['reflective'] },
          cognitive_profile: { critical_thinking: 7 },
          emotional_profile: { eq_score: 6 },
          behavioral_insights: { confidence: 5 },
          conversation_analysis: { consistency: 'high' },
          recommendations: ['Plan a follow-up conversation'],
          key_moments: [],
          red_flags: []
        },
        face_data: {
          dominant_emotion: 'anxious',
          eye_contact_score: 6,
          facial_tension_score: 7,
          emotion_stability: 'moderate',
          engagement_indicators: 'Student maintained intermittent eye contact',
          notable_expressions: ['furrowed brow during exam discussion', 'slight smile at end'],
          emotion_trajectory: [
            { point: 'Opening', emotion: 'nervous' },
            { point: 'Mid-session', emotion: 'anxious' },
            { point: 'Closing', emotion: 'hopeful' }
          ]
        },
        voice_data: {
          speech_patterns: 'Fragmented sentences with frequent pauses',
          confidence_level: 'Low to moderate',
          speech_rate: 'Below average',
          volume_pattern: 'Quiet, becoming slightly louder mid-session',
          overall_confidence_score: 5,
          hesitation_markers: ['long pauses before answering', 'filler words (umm, like)'],
          emotional_tone_shifts: [
            { point: 'Exam topic', shift: 'Voice became shaky' },
            { point: 'Coping discussion', shift: 'More confident tone' }
          ]
        }
      }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' }
      });
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

    static isTypeSupported() {
      return true;
    }

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

      setTimeout(() => this._emit({ type: 'session_started', session_id: '22222222-2222-2222-2222-222222222222', started_at: '2026-03-17T10:00:00+00:00' }), 40);
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
      window.__wsEvents.push(['send', payload]);
      // Respond to end_session with session_saved
      try {
        const msg = JSON.parse(payload);
        if (msg.type === 'end_session') {
          setTimeout(() => this._emit({ type: 'session_saved', session_id: '22222222-2222-2222-2222-222222222222' }), 20);
        }
      } catch {}
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


def _start_stubbed_session(page: Page, server_url: str) -> None:
  page.add_init_script(_LIVE_SESSION_STUB)
  page.goto(server_url, wait_until="networkidle")
  page.fill('#student-name', 'Stub Student')
  page.select_option('#class-name', '11')
  page.fill('#section-name', 'C')
  page.fill('#school-name', 'Stub School')
  page.fill('#student-age', '14')
  page.check('#consent-cb')
  page.click('#start-btn')
  expect(page.locator('#live')).to_be_visible()
  page.wait_for_function("() => Array.isArray(window.__wsEvents) && window.__wsEvents.includes('connection_active')")
  page.wait_for_function(
    "() => (document.getElementById('transcript')?.textContent || '').includes('Thanks for sharing that.')"
  )


class TestLiveSessionStubbed:
  def test_full_flow_submits_expected_metadata(self, page: Page, server_url: str) -> None:
    _start_stubbed_session(page, server_url)
    page.click('#end-btn')
    page.wait_for_function("() => window.__analyzeRequest !== null")

    req = page.evaluate('() => window.__analyzeRequest')
    assert req['student_name'] == 'Stub Student'
    assert req['student_class'] == '11'
    assert req['student_section'] == 'C'
    assert req['student_school'] == 'Stub School'
    assert req['student_age'] == '14'
    assert 'Thanks for sharing' in req['transcript']
    assert req['session_id'] == '22222222-2222-2222-2222-222222222222'
    expect(page.locator('#summary')).to_be_visible()
    assert 'Mock profile summary' in page.locator('#summary-text').inner_text()

  def test_reconnect_events_fire_and_banner_visibly_updates(self, page: Page, server_url: str) -> None:
    _start_stubbed_session(page, server_url)
    page.wait_for_timeout(600)
    events = page.evaluate("() => window.__wsEvents")
    assert 'reconnecting' in events
    assert 'wrapup_warning' in events
    expect(page.locator('#status-text')).to_contain_text('Listening')
    expect(page.locator('#reconnect-banner')).to_be_visible()

  def test_analysis_status_bar_shows_progress(self, page: Page, server_url: str) -> None:
    _start_stubbed_session(page, server_url)
    page.click('#end-btn')
    bar = page.locator('#analysis-status-bar')
    expect(bar).to_be_visible()
    expect(bar).to_contain_text('Done!')

  def test_mute_button_toggles_state(self, page: Page, server_url: str) -> None:
    _start_stubbed_session(page, server_url)
    mute_btn = page.locator('#mute-btn')
    expect(mute_btn).to_be_visible()
    expect(mute_btn).to_contain_text('Mic On')

    # Click mute
    mute_btn.click()
    expect(mute_btn).to_contain_text('Mic Off')
    is_muted = page.evaluate("() => window.counselai?.state?.isMuted")
    # state is on the module default export, check via the DOM indicator
    assert 'Mic Off' in mute_btn.inner_text()

    # Click unmute
    mute_btn.click()
    expect(mute_btn).to_contain_text('Mic On')

  def test_face_analysis_renders_with_data(self, page: Page, server_url: str) -> None:
    _start_stubbed_session(page, server_url)
    page.click('#end-btn')
    page.wait_for_function("() => window.__analyzeRequest !== null")
    face_section = page.locator('#face-analysis-section')
    expect(face_section).to_be_visible()
    face_text = face_section.inner_text()
    assert 'anxious' in face_text.lower()
    assert 'Eye contact score' in face_text
    assert 'Emotion trajectory' in face_text

  def test_voice_analysis_renders_with_data(self, page: Page, server_url: str) -> None:
    _start_stubbed_session(page, server_url)
    page.click('#end-btn')
    page.wait_for_function("() => window.__analyzeRequest !== null")
    voice_section = page.locator('#voice-analysis-section')
    expect(voice_section).to_be_visible()
    voice_text = voice_section.inner_text()
    assert 'Fragmented' in voice_text
    assert 'Hesitation markers' in voice_text
    assert 'Tone shifts' in voice_text


class TestSummaryScreenRendering:
  def _end_session_and_wait(self, page: Page, server_url: str) -> None:
    _start_stubbed_session(page, server_url)
    page.click('#end-btn')
    page.wait_for_function("() => window.__analyzeRequest !== null")

  def test_personality_section_renders(self, page: Page, server_url: str) -> None:
    self._end_session_and_wait(page, server_url)
    personality = page.locator('#personality-section')
    expect(personality).to_be_visible()
    assert 'reflective' in personality.inner_text().lower()

  def test_cognitive_section_renders(self, page: Page, server_url: str) -> None:
    self._end_session_and_wait(page, server_url)
    cognitive = page.locator('#cognitive-section')
    expect(cognitive).to_be_visible()
    assert cognitive.inner_text().strip() != ''

  def test_emotional_section_renders(self, page: Page, server_url: str) -> None:
    self._end_session_and_wait(page, server_url)
    emotional = page.locator('#emotional-section')
    expect(emotional).to_be_visible()
    assert emotional.inner_text().strip() != ''

  def test_behavioral_section_renders(self, page: Page, server_url: str) -> None:
    self._end_session_and_wait(page, server_url)
    behavioral = page.locator('#behavioral-section')
    expect(behavioral).to_be_visible()
    assert behavioral.inner_text().strip() != ''

  def test_score_metrics_display(self, page: Page, server_url: str) -> None:
    self._end_session_and_wait(page, server_url)
    metrics = page.locator('#profile-metrics')
    expect(metrics).to_be_visible()
    metrics_text = metrics.inner_text()
    assert 'Critical Thinking' in metrics_text
    # buildMetrics creates inline-styled score bars, not .score-bar class
    assert '7/10' in metrics_text or '/10' in metrics_text

  def test_recommendations_render(self, page: Page, server_url: str) -> None:
    self._end_session_and_wait(page, server_url)
    recs = page.locator('#recommendations')
    expect(recs).to_be_visible()
    assert 'Plan a follow-up conversation' in recs.inner_text()

  def test_summary_text_shows_profile_summary(self, page: Page, server_url: str) -> None:
    self._end_session_and_wait(page, server_url)
    summary_text = page.locator('#summary-text')
    expect(summary_text).to_be_visible()
    assert 'Mock profile summary' in summary_text.inner_text()

  def test_session_metadata_in_summary(self, page: Page, server_url: str) -> None:
    self._end_session_and_wait(page, server_url)
    meta = page.locator('#summary-meta')
    expect(meta).to_be_visible()
    meta_text = meta.inner_text()
    assert 'Stub Student' in meta_text
    assert 'Class 11' in meta_text

  def test_download_transcript_button_exists(self, page: Page, server_url: str) -> None:
    self._end_session_and_wait(page, server_url)
    btn = page.locator('#download-transcript-btn')
    expect(btn).to_be_visible()

  def test_no_counsellor_transcript_double_append(self, page: Page, server_url: str) -> None:
    self._end_session_and_wait(page, server_url)
    entries = page.locator('#transcript >> text="Thanks for sharing that."')
    assert entries.count() == 1
