/**
 * CounselAI Live — entry point.
 *
 * Consolidates: state.js, screens.js, ui.js, and the original app.js
 * into a single module. All previously-exported symbols are re-exported
 * so that session.js, media.js, and analysis.js can import from './app.js'.
 */

// ============================================================
// STATE — shared mutable state for the live session
// ============================================================

const state = {
  // Media
  mediaStream: null,
  recorder: null,
  recordedChunks: [],

  // Timer
  timerStart: null,
  timerHandle: null,

  // Transcript
  currentAiEntry: null,
  transcriptEntries: [],
  currentStudentEntry: null,
  studentTranscriptTimer: null,
  lastStudentTranscript: '',
  waitingForStudentTranscript: false,
  lastUserItemId: null,

  // Session
  sessionMeta: null,
  eventCount: 0,
  geminiModelTurnCount: 0,
  intentionalSessionEnd: false,

  // Session ID from server (for linking analysis to session)
  savedSessionId: null,
  pendingTranscriptFlush: null,

  // Gemini
  geminiWs: null,
  geminiAudioCtx: null,
  geminiPlaybackCtx: null,
  geminiPlaybackTime: 0,
  geminiMicProcessor: null,
  geminiVideoInterval: null,
  geminiReconnecting: false,
  geminiConnectionState: 'CLOSED',
  audioChunksPlayed: 0,

  // Event tracking
  eventTypeCounts: {},

  // Mute state
  isMuted: false,
};

export default state;

// ============================================================
// SCREENS — show/hide the three main screens + DOM refs
// ============================================================

const screens = {
  welcome: document.getElementById('welcome'),
  live: document.getElementById('live'),
  summary: document.getElementById('summary'),
};

export function showScreen(name) {
  Object.values(screens).forEach(s => s.classList.add('hidden'));
  if (screens[name]) screens[name].classList.remove('hidden');
}

// DOM element refs used across modules
export const dom = {
  statusText: document.getElementById('status-text'),
  statusDot: document.getElementById('status-dot'),
  timerEl: document.getElementById('timer'),
  transcriptEl: document.getElementById('transcript'),
  orb: document.getElementById('orb'),
  preview: document.getElementById('preview'),
  previewWrap: document.getElementById('preview-wrap'),
  aiAudio: document.getElementById('ai-audio'),
  enableAudioBtn: document.getElementById('enable-audio-btn'),
  rtcDebug: document.getElementById('rtc-debug'),
  toast: document.getElementById('toast'),
  caseStudyText: document.getElementById('case-study-text'),
  profileMetrics: document.getElementById('profile-metrics'),
  personalitySection: document.getElementById('personality-section'),
  cognitiveSection: document.getElementById('cognitive-section'),
  emotionalSection: document.getElementById('emotional-section'),
  behavioralSection: document.getElementById('behavioral-section'),
  conversationSection: document.getElementById('conversation-section'),
  recommendationsEl: document.getElementById('recommendations'),
};

// Expose showScreen globally for tests that call it directly
window.showScreen = showScreen;

// ============================================================
// UI — status, toast, logging, debug, formatting
// ============================================================

export function setConnectionState(newState) {
  state.geminiConnectionState = newState;
  uiLog('INFO', `Connection state: ${newState}`);
  const banner = document.getElementById('reconnect-banner');
  dom.statusDot.classList.remove('speaking', 'reconnecting', 'error');
  if (newState === 'RECONNECTING') {
    dom.statusDot.classList.add('reconnecting');
    banner.classList.add('visible');
  } else if (newState === 'ERROR') {
    dom.statusDot.classList.add('error');
    banner.classList.remove('visible');
  } else {
    banner.classList.remove('visible');
  }
}

export function setStatus(text) {
  dom.statusText.textContent = text;
  if (dom.statusDot) {
    dom.statusDot.classList.remove('speaking');
    if (text === 'Speaking...') dom.statusDot.classList.add('speaking');
  }
}

export function showToast(msg) {
  dom.toast.textContent = msg;
  dom.toast.style.display = 'block';
  setTimeout(() => { dom.toast.style.display = 'none'; }, 4000);
}

export function formatTime(ms) {
  const s = Math.floor(ms / 1000);
  const m = String(Math.floor(s / 60)).padStart(2, '0');
  const r = String(s % 60).padStart(2, '0');
  return `${m}:${r}`;
}

export function setDebug(text) {
  dom.rtcDebug.textContent = text;
}

export function uiLog(level, ...args) {
  const el = document.getElementById('event-log');
  const ts = new Date().toLocaleTimeString('en-GB', { hour12: false });
  const prefix = level === 'WARN' ? '\u26a0\ufe0f' : level === 'OK' ? '\u2705' : level === 'ERR' ? '\u274c' : '\u2139\ufe0f';
  const msg = args.map(a => typeof a === 'object' ? JSON.stringify(a, null, 1) : String(a)).join(' ');
  const line = `[${ts}] ${prefix} ${msg}\n`;
  if (el) { el.textContent += line; el.scrollTop = el.scrollHeight; }
  if (level === 'WARN' || level === 'ERR') console.warn('[CounselAI]', ...args);
  else console.log('[CounselAI]', ...args);
}

export function updateDebugSnapshot() {
  const wsState = state.geminiWs ? ['CONNECTING', 'OPEN', 'CLOSING', 'CLOSED'][state.geminiWs.readyState] : 'none';
  const recState = state.recorder ? state.recorder.state : 'none';
  setDebug(`Gemini WS ${wsState} | Rec ${recState} | Events ${state.eventCount} | Chunks ${state.recordedChunks.length} | Transcript ${state.transcriptEntries.length}`);
}

export function tryPlayAiAudio() {
  if (!dom.aiAudio.srcObject) return;
  dom.aiAudio.play().then(() => {
    dom.enableAudioBtn.style.display = 'none';
  }).catch(() => {
    dom.enableAudioBtn.style.display = 'inline-flex';
    setStatus('Tap "Enable counsellor audio"');
  });
}

export function logRealtimeEvent(msg) {
  state.eventCount += 1;
  const type = msg && msg.type ? msg.type : 'unknown';
  state.eventTypeCounts[type] = (state.eventTypeCounts[type] || 0) + 1;
  console.log(`[CounselAI] Event #${state.eventCount}: ${type}`, msg);
  if (/(transcript|input|user)/i.test(type)) {
    try { console.log(`[CounselAI] Event payload (${type}):\n${JSON.stringify(msg, null, 2)}`); } catch {}
  }
  updateDebugSnapshot();
}

// ============================================================
// APP — initialization, event listeners, case study loading
// ============================================================

import { setupMedia, setupRecorder } from './media.js';
import { startGeminiSession } from './session.js';
import { endSession } from './analysis.js';

// --- Start session ---

async function startSession() {
  const name = document.getElementById('student-name').value.trim() || 'Student';
  const className = document.getElementById('class-name').value.trim() || 'Class';
  const section = document.getElementById('section-name').value.trim();
  const school = document.getElementById('school-name').value.trim();
  const age = Number(document.getElementById('student-age').value || 15);
  const scenario = document.getElementById('case-study').value;
  const lang = document.getElementById('session-lang').value || 'hinglish';

  state.sessionMeta = { name, className, section, school, age, scenario, lang, start: new Date() };
  state.recordedChunks = [];
  state.transcriptEntries = [];
  state.currentAiEntry = null;
  state.eventCount = 0;
  state.lastStudentTranscript = '';
  state.audioChunksPlayed = 0;
  state.savedSessionId = null;
  state.pendingTranscriptFlush = null;
  state.intentionalSessionEnd = false;
  dom.transcriptEl.innerHTML = '';
  dom.enableAudioBtn.style.display = 'none';
  dom.aiAudio.srcObject = null;

  showScreen('live');
  setStatus('Connecting...');
  setDebug('Gemini: connecting');
  dom.caseStudyText.textContent = scenario || 'No case study loaded.';

  const hasVideoTrack = await setupMedia();
  setupRecorder(hasVideoTrack);

  state.geminiPlaybackCtx = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 24000 });
  state.geminiPlaybackCtx.resume().then(() => uiLog('OK', 'Playback AudioContext resumed'));
  state.geminiPlaybackTime = 0;
  await startGeminiSession(name, scenario);

  state.timerStart = Date.now();
  state.timerHandle = setInterval(() => {
    dom.timerEl.textContent = formatTime(Date.now() - state.timerStart);
  }, 500);
  setStatus('Listening...');
  updateDebugSnapshot();
}

// --- Event listeners ---

document.getElementById('start-btn').addEventListener('click', () => {
  startSession().catch(err => { showToast(err.message); showScreen('welcome'); });
});

document.getElementById('end-btn').addEventListener('click', endSession);
dom.enableAudioBtn.addEventListener('click', () => tryPlayAiAudio());
document.getElementById('new-btn').addEventListener('click', () => location.reload());

// Mute button
const muteBtn = document.getElementById('mute-btn');
if (muteBtn) {
  muteBtn.addEventListener('click', () => {
    state.isMuted = !state.isMuted;
    muteBtn.innerHTML = state.isMuted ? '&#x1f507; Mic Off' : '&#x1f3a4; Mic On';
    muteBtn.classList.toggle('btn-warning', state.isMuted);
    uiLog('INFO', state.isMuted ? 'Microphone muted — audio stopped to Gemini' : 'Microphone unmuted — audio resumed');
  });
}

// Consent checkbox gates the start button
const consentCb = document.getElementById('consent-cb');
const startBtn = document.getElementById('start-btn');
if (consentCb && startBtn) {
  startBtn.disabled = true;
  consentCb.addEventListener('change', () => { startBtn.disabled = !consentCb.checked; });
}

// --- Load case studies ---

(async () => {
  try {
    const r = await fetch('/api/case-studies');
    const d = await r.json();
    const sel = document.getElementById('case-study');
    sel.innerHTML = '';
    d.case_studies.forEach(cs => {
      const o = document.createElement('option');
      o.value = cs.scenario_text;
      o.textContent = cs.id + ' \u2022 ' + cs.title + ' (' + cs.target_class + ')';
      sel.appendChild(o);
    });
    if (sel.value) dom.caseStudyText.textContent = sel.value;
    sel.addEventListener('change', () => { dom.caseStudyText.textContent = sel.value; });
  } catch {
    showToast('Failed to load case studies');
  }
})();
