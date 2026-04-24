/**
 * Post-session analysis — endSession + driving the shared report renderer
 * (see /static/report-renderer.js, which exposes window.renderReport).
 */
import state from './state.js';
import { dom, showScreen } from './state.js';
import { setStatus, showToast, formatTime, uiLog } from './app.js';
import { stopWaveform, finalizeRecording, finalizeMixedRecording } from './media.js';
import { waitForSessionSaved } from './session.js';

// Listen for session timeout events dispatched by session.js
window.addEventListener('counselai:session_timeout', () => endSession());

// ── Full-screen report generation overlay ──────────────────────────────

const OVERLAY_STEPS = [
  'Saving your session…',
  'Uploading session data…',
  'Scoring 9 dimensions…',
  'Running career engine…',
  'Assembling your report…',
  'Report ready!',
];

function ensureOverlay() {
  let el = document.getElementById('rgo');
  if (el) return el;

  // Inject keyframes + styles once
  if (!document.getElementById('rgo-css')) {
    const css = document.createElement('style');
    css.id = 'rgo-css';
    css.textContent = `
      #rgo {
        position: fixed; inset: 0; z-index: 99999;
        display: flex; align-items: center; justify-content: center;
        background: linear-gradient(160deg, #0F172A 0%, #1E1B4B 55%, #0C1015 100%);
        font-family: 'Outfit', system-ui, sans-serif;
        transition: opacity 0.7s ease;
      }
      .rgo-card {
        display: flex; flex-direction: column; align-items: center;
        gap: 24px; padding: 52px 44px; text-align: center; max-width: 400px;
      }
      .rgo-brand {
        font-family: 'Plus Jakarta Sans', system-ui, sans-serif;
        font-size: 1.7rem; font-weight: 800; letter-spacing: -0.04em; color: #fff;
      }
      .rgo-brand span {
        background: linear-gradient(135deg, #A5B4FC, #818CF8);
        -webkit-background-clip: text; -webkit-text-fill-color: transparent;
        background-clip: text;
      }
      .rgo-rings {
        position: relative; width: 88px; height: 88px;
        display: flex; align-items: center; justify-content: center;
      }
      .rgo-ring {
        position: absolute; border-radius: 50%;
        border: 1.5px solid rgba(129,140,248,.22);
        animation: rgoPulse 2.4s ease-in-out infinite;
      }
      .rgo-ring-1 { width: 88px; height: 88px; animation-delay: 0s; }
      .rgo-ring-2 { width: 68px; height: 68px; animation-delay: 0.5s; }
      .rgo-ring-3 { width: 50px; height: 50px; animation-delay: 1s; }
      .rgo-spinner {
        width: 36px; height: 36px;
        border: 2.5px solid rgba(165,180,252,.12);
        border-top-color: #818CF8;
        border-radius: 50%;
        animation: rgoSpin 0.8s linear infinite;
      }
      .rgo-step-wrap { min-height: 56px; display: flex; align-items: center; justify-content: center; }
      .rgo-step {
        font-size: 1.05rem; font-weight: 600; color: #C7D2FE;
        line-height: 1.5; max-width: 280px;
        transition: opacity 0.25s ease, transform 0.25s ease;
      }
      .rgo-step.fading { opacity: 0; transform: translateY(-6px); }
      .rgo-track {
        width: 260px; height: 3px;
        background: rgba(255,255,255,.07); border-radius: 2px; overflow: hidden;
      }
      .rgo-fill {
        height: 100%; width: 0%;
        background: linear-gradient(90deg, #4F46E5, #A5B4FC);
        border-radius: 2px;
        transition: width 0.6s cubic-bezier(0.4,0,0.2,1);
      }
      .rgo-pct {
        font-family: 'JetBrains Mono', monospace; font-size: 0.72rem;
        color: rgba(165,180,252,.6); letter-spacing: 0.04em;
      }
      .rgo-sub {
        font-size: 0.65rem; color: rgba(100,116,139,.55);
        letter-spacing: 0.1em; text-transform: uppercase;
      }
      @keyframes rgoSpin  { to { transform: rotate(360deg); } }
      @keyframes rgoPulse {
        0%,100% { transform: scale(0.88); opacity: 0.4; }
        50%      { transform: scale(1);    opacity: 0.15; }
      }
    `;
    document.head.appendChild(css);
  }

  el = document.createElement('div');
  el.id = 'rgo';
  el.innerHTML = `
    <div class="rgo-card">
      <div class="rgo-brand">Counsel<span>AI</span></div>
      <div class="rgo-rings">
        <div class="rgo-ring rgo-ring-1"></div>
        <div class="rgo-ring rgo-ring-2"></div>
        <div class="rgo-ring rgo-ring-3"></div>
        <div class="rgo-spinner" id="rgo-spinner"></div>
      </div>
      <div class="rgo-step-wrap">
        <div class="rgo-step" id="rgo-step">Preparing…</div>
      </div>
      <div class="rgo-track"><div class="rgo-fill" id="rgo-fill"></div></div>
      <div class="rgo-pct" id="rgo-pct">0%</div>
      <div class="rgo-sub">Please wait — do not close this tab</div>
    </div>
  `;
  document.body.appendChild(el);
  return el;
}

function setOverlayStep(stepIndex, detail) {
  ensureOverlay();
  const stepEl = document.getElementById('rgo-step');
  const fillEl = document.getElementById('rgo-fill');
  const pctEl  = document.getElementById('rgo-pct');
  const pct = Math.min(95, Math.round((stepIndex / (OVERLAY_STEPS.length - 1)) * 100));
  const label = OVERLAY_STEPS[stepIndex] || detail || 'Processing…';
  const text  = detail ? `${label} — ${detail}` : label;

  if (stepEl) {
    stepEl.classList.add('fading');
    setTimeout(() => {
      stepEl.textContent = text;
      stepEl.classList.remove('fading');
    }, 260);
  }
  if (fillEl) fillEl.style.width = pct + '%';
  if (pctEl)  pctEl.textContent  = pct + '%';
}

function setOverlayError(msg) {
  ensureOverlay();
  const stepEl   = document.getElementById('rgo-step');
  const fillEl   = document.getElementById('rgo-fill');
  const spinner  = document.getElementById('rgo-spinner');
  const subEl    = document.querySelector('#rgo .rgo-sub');
  if (stepEl)  { stepEl.textContent = msg; stepEl.style.color = '#FCA5A5'; }
  if (fillEl)  { fillEl.style.background = 'linear-gradient(90deg,#E11D48,#F43F5E)'; fillEl.style.width = '100%'; }
  if (spinner) { spinner.style.borderTopColor = '#F43F5E'; spinner.style.animationPlayState = 'paused'; }
  if (subEl)   subEl.textContent = 'You may close this tab';
}

function hideOverlay() {
  const el     = document.getElementById('rgo');
  const fillEl = document.getElementById('rgo-fill');
  const pctEl  = document.getElementById('rgo-pct');
  const spinner = document.getElementById('rgo-spinner');
  if (!el) return;
  if (fillEl)  fillEl.style.width = '100%';
  if (pctEl)   pctEl.textContent  = '100%';
  if (spinner) { spinner.style.borderTopColor = '#34D399'; }
  setTimeout(() => {
    el.style.opacity = '0';
    setTimeout(() => { el.remove(); document.getElementById('rgo-css')?.remove(); }, 750);
  }, 500);
}

// ── Helpers ─────────────────────────────────────────────────────────────

function collectFinalTranscriptEntries() {
  const entries = state.transcriptEntries
    .filter(e => e && e.text && e.text.trim())
    .map(e => ({ role: e.role, text: e.text.trim() }));
  if (entries.length) return entries;
  dom.transcriptEl.querySelectorAll('.entry').forEach(el => {
    const role = el.classList.contains('ai') ? 'counsellor' : 'student';
    const bodyEl = el.querySelector('.body') || el.querySelector('div:last-child');
    const text = bodyEl ? bodyEl.textContent.trim() : '';
    if (text) entries.push({ role, text });
  });
  return entries;
}

function describeRecordingIssue(mediaStatus) {
  const diagChunks = mediaStatus.chunkCount || 0;
  const zeroByteChunks = mediaStatus.zeroByteChunkCount || 0;
  if (!mediaStatus.recorderStarted) return 'Recording was empty: recorder never started.';
  if ((mediaStatus.dataEventCount || 0) === 0) return 'Recording was empty: no data events were captured.';
  if (diagChunks === 0 && zeroByteChunks > 0) return 'Recording was empty: the recorder only produced empty chunks.';
  if (diagChunks === 0) return 'Recording was empty: no chunks were captured (the tab may have been backgrounded).';
  return 'Recording was empty: captured chunks could not be finalized.';
}

function showAnalysisUnavailable(message) {
  const snapshotText = document.getElementById('rpt-snapshot-text');
  if (snapshotText) snapshotText.textContent = message || 'Analysis unavailable.';
}

// ── End session ─────────────────────────────────────────────────────────

export async function endSession() {
  state.intentionalSessionEnd = true;
  setStatus('Processing...');
  clearInterval(state.timerHandle);
  stopWaveform();

  // Show full-screen overlay immediately — user cannot miss this
  setOverlayStep(0);

  if (state.geminiPlaybackCtx) {
    try { state.geminiPlaybackCtx.suspend(); } catch {}
  }

  if (dom.preview) { dom.preview.srcObject = null; dom.preview.pause(); }
  if (state.mediaStream) {
    state.mediaStream.getTracks().forEach(t => t.stop());
    state.mediaStream = null;
  }

  const [videoBlob, mixedBlob] = await Promise.all([finalizeRecording(), finalizeMixedRecording()]);

  if (state.geminiVideoInterval) { clearInterval(state.geminiVideoInterval); state.geminiVideoInterval = null; }
  if (state.geminiTranscriptTimer) { clearTimeout(state.geminiTranscriptTimer); state.geminiTranscriptTimer = null; }
  if (state.geminiMicProcessor) { try { state.geminiMicProcessor.disconnect(); } catch {} state.geminiMicProcessor = null; }

  if (state.geminiWs && state.geminiWs.readyState === WebSocket.OPEN) {
    try { state.geminiWs.send(JSON.stringify({ type: 'end_session' })); } catch {}
    await waitForSessionSaved(5000);
  }

  if (state.geminiAudioCtx) { try { state.geminiAudioCtx.close(); } catch {} state.geminiAudioCtx = null; }
  if (state.geminiPlaybackCtx) { try { state.geminiPlaybackCtx.close(); } catch {} state.geminiPlaybackCtx = null; }
  if (state.mixedRecordingCtx) { try { state.mixedRecordingCtx.close(); } catch {} state.mixedRecordingCtx = null; }
  if (state.geminiWs) { try { state.geminiWs.close(); } catch {} state.geminiWs = null; }

  const duration = formatTime(Date.now() - state.timerStart);
  const summaryMetaBase = `${state.sessionMeta.name} \u2022 Class ${state.sessionMeta.className} \u2022 ${duration}`;
  document.getElementById('summary-meta').textContent = summaryMetaBase;

  const summaryTranscriptEl = document.getElementById('summary-transcript');
  // Normalize whitespace so this view matches the dashboard rendering.
  // Gemini transcript chunks may contain stray newlines / double spaces;
  // collapse them to single spaces before joining turns with newlines.
  const cleanText = t => (t || '').replace(/\s+/g, ' ').trim();
  const safeTranscriptEntries = state.transcriptEntries.filter(e => e && e.text && e.text.trim());
  const formatTranscriptForDisplay = entries => entries.map(e => `${e.role === 'counsellor' ? 'Counsellor' : 'Student'}: ${cleanText(e.text)}`).join('\n');
  summaryTranscriptEl.textContent = safeTranscriptEntries.length ? formatTranscriptForDisplay(safeTranscriptEntries) : dom.transcriptEl.textContent.trim();

  const existingDl = document.getElementById('download-transcript-btn');
  if (!existingDl) {
    const dlBtn = document.createElement('button');
    dlBtn.id = 'download-transcript-btn';
    dlBtn.className = 'btn btn-ghost';
    dlBtn.style.cssText = 'width:auto;min-width:180px;margin-top:12px;';
    dlBtn.textContent = 'Download transcript';
    dlBtn.addEventListener('click', () => {
      const text = safeTranscriptEntries.map(e => `${e.role === 'counsellor' ? 'Counsellor' : 'Student'}: ${cleanText(e.text)}`).join('\n\n');
      const blob = new Blob([text], { type: 'text/plain' });
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = `counselai-transcript-${state.sessionMeta.name.replace(/\s+/g, '_')}.txt`;
      a.click();
      URL.revokeObjectURL(a.href);
    });
    const summaryGrid = document.querySelector('.summary-grid');
    if (summaryGrid) summaryGrid.parentElement.insertBefore(dlBtn, summaryGrid.nextSibling);

    if (mixedBlob && mixedBlob.size > 0) {
      const dlRecBtn = document.createElement('button');
      dlRecBtn.id = 'download-recording-btn';
      dlRecBtn.className = 'btn btn-ghost';
      dlRecBtn.style.cssText = 'width:auto;min-width:180px;margin-top:12px;margin-left:8px;';
      dlRecBtn.textContent = 'Download recording';
      dlRecBtn.addEventListener('click', () => {
        const a = document.createElement('a');
        a.href = URL.createObjectURL(mixedBlob);
        a.download = `counselai-recording-${state.sessionMeta.name.replace(/\s+/g, '_')}.webm`;
        a.click();
        URL.revokeObjectURL(a.href);
      });
      dlBtn.insertAdjacentElement('afterend', dlRecBtn);
    }
  }

  showScreen('summary');

  if (!state.savedSessionId) {
    uiLog('ERR', 'No session_id received from server \u2014 cannot submit analysis.');
    setOverlayError('Session was not saved by the server. Analysis cannot proceed.');
    showToast('Session save failed. Please try again or contact support.');
    showAnalysisUnavailable('No session_id available \u2014 the server did not confirm the session was saved.');
    return;
  }

  try {
    const fd = new FormData();
    const finalTranscript = collectFinalTranscriptEntries();
    const hasTranscriptData = finalTranscript.length > 0;
    const mediaStatus = state.sessionMeta?.mediaStatus || {};
    const hasVideoPayload = Boolean(videoBlob && videoBlob.size > 0);
    const transcriptOnlyFallback = !hasVideoPayload && hasTranscriptData;
    const detailText = hasVideoPayload
      ? `Video: ${(videoBlob.size / 1024).toFixed(0)} KB`
      : transcriptOnlyFallback
        ? 'Transcript-only mode'
        : 'No recording captured';
    setOverlayStep(1, detailText);

    if (!hasVideoPayload) {
      const diagMsg = describeRecordingIssue(mediaStatus);
      console.info(`[CounselAI] Media fallback: ${diagMsg}`, mediaStatus);
      mediaStatus.analysisMode = hasTranscriptData ? 'transcript_only' : 'capture_failed';
      if (!hasTranscriptData) {
        setOverlayError(diagMsg);
        showAnalysisUnavailable('No usable recording or transcript was captured. Keep this tab in focus and try again.');
        showToast(diagMsg);
        return;
      }
      document.getElementById('summary-meta').textContent = `${summaryMetaBase} \u2022 Transcript-only analysis`;
      showToast('No video captured; analysis will continue using transcript data only.');
    } else {
      mediaStatus.analysisMode = 'multimodal';
    }

    if (hasVideoPayload) fd.append('video', videoBlob, 'session.webm');
    fd.append('transcript', JSON.stringify(finalTranscript));
    fd.append('student_name', state.sessionMeta.name);
    fd.append('student_class', state.sessionMeta.className);
    fd.append('student_section', state.sessionMeta.section || '');
    fd.append('student_school', state.sessionMeta.school || '');
    fd.append('student_age', String(state.sessionMeta.age || 15));
    fd.append('session_start_time', state.sessionMeta.start.toISOString());
    fd.append('session_end_time', new Date().toISOString());
    if (state.savedSessionId) fd.append('session_id', state.savedSessionId);

    setOverlayStep(2, `${finalTranscript.length} turns`);
    const resp = await fetch('/api/analyze-session', { method: 'POST', body: fd });
    if (resp.ok) {
      setOverlayStep(4, 'Rendering…');
      const data = await resp.json();
      if (typeof window.renderReport === 'function') {
        window.renderReport(data.report || {});
      } else {
        console.error('[CounselAI] window.renderReport not loaded');
      }
      hideOverlay();
    } else {
      const errText = (await resp.text().catch(() => 'Unknown error')).trim();
      const errMsg = errText || `HTTP ${resp.status}`;
      setOverlayError(`Analysis failed: ${errMsg}`);
      console.error('[CounselAI] Analysis HTTP error:', resp.status, errText);
      showAnalysisUnavailable(`Analysis unavailable: ${errMsg}`);
      showToast(`Analysis failed: ${errMsg}`);
    }
  } catch (err) {
    console.error('[CounselAI] Analysis error:', err);
    setOverlayError(`Error: ${err.message}`);
    showAnalysisUnavailable(`Analysis unavailable: ${err.message}`);
  }
}
