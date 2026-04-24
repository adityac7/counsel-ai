/**
 * CounselAI Live — entry point.
 *
 * State + DOM refs live in state.js (no imports, no cycles).
 * This module provides UI helpers and wires up event listeners.
 */

import state from './state.js';
import { dom, showScreen } from './state.js';

// Re-export state and state.js symbols so existing callers that
// import from './app.js' continue to work without changes.
export default state;
export { dom, showScreen };

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
  updateDebugSnapshot();
}

// ============================================================
// APP — case studies, filtering, validation, session screens
// ============================================================

import { setupMedia, setupRecorder } from './media.js';
import { startGeminiSession } from './session.js';
import { endSession } from './analysis.js';

// Module-level store of all case studies from the API
let allCaseStudies = [];

// ── Case study helpers ────────────────────────────────────────

/** Return scenario text in the selected language. */
function getScenarioDisplay(cs, lang) {
  if (lang === 'hi' && cs.scenario_text_hi) return cs.scenario_text_hi;
  return cs.scenario_text;
}

/** Return the group for a given class value ("8"→"8-10", "11"→"11-12"). */
function classToGroup(classVal) {
  return (classVal === '8' || classVal === '9' || classVal === '10') ? '8-10' : '11-12';
}

/** Repopulate the case study dropdown based on current class + language. */
function filterAndPopulateCaseStudies() {
  const classVal = document.getElementById('class-name').value;
  const lang = document.getElementById('session-lang').value;
  const group = classToGroup(classVal);
  const sel = document.getElementById('case-study');
  const prevId = sel.value;

  sel.innerHTML = '';
  const filtered = allCaseStudies.filter(cs => cs.target_class === group);
  filtered.forEach(cs => {
    const o = document.createElement('option');
    o.value = cs.id;
    o.textContent = `${cs.title} (${cs.category})`;
    sel.appendChild(o);
  });

  // Preserve selection if still valid
  if (prevId && filtered.find(cs => cs.id === prevId)) {
    sel.value = prevId;
  }

  // Update scenario preview text
  const selected = filtered.find(cs => cs.id === sel.value);
  if (selected && dom.caseStudyText) {
    dom.caseStudyText.textContent = getScenarioDisplay(selected, lang);
  }

  checkValidity();
}

// ── Form validation ───────────────────────────────────────────

function showFieldError(fieldId, message) {
  const field = document.getElementById(fieldId);
  if (!field) return;
  field.classList.add('input-error');
  const existing = field.parentElement.querySelector('.field-error');
  if (existing) existing.remove();
  const err = document.createElement('span');
  err.className = 'field-error';
  err.textContent = message;
  field.parentElement.appendChild(err);
}

function clearFieldError(fieldId) {
  const field = document.getElementById(fieldId);
  if (!field) return;
  field.classList.remove('input-error');
  const err = field.parentElement.querySelector('.field-error');
  if (err) err.remove();
}

/** Check validity and update button state — no error UI changes. */
function checkValidity() {
  const name = document.getElementById('student-name').value.trim();
  const school = document.getElementById('school-name').value.trim();
  const caseStudy = document.getElementById('case-study').value;
  const consent = document.getElementById('consent-cb').checked;
  const valid = !!(name && school && caseStudy && consent);
  document.getElementById('start-btn').disabled = !valid;
  return valid;
}

/** Show all errors — called only on submit attempt. */
function validateForm() {
  const name = document.getElementById('student-name').value.trim();
  const school = document.getElementById('school-name').value.trim();
  const caseStudy = document.getElementById('case-study').value;
  const consent = document.getElementById('consent-cb').checked;

  let valid = true;

  if (!name) { showFieldError('student-name', 'Please enter your name'); valid = false; }
  else clearFieldError('student-name');

  if (!school) { showFieldError('school-name', 'Please enter your school name'); valid = false; }
  else clearFieldError('school-name');

  if (!caseStudy) { showFieldError('case-study', 'Please select a case study'); valid = false; }
  else clearFieldError('case-study');

  const consentRow = document.getElementById('consent-row');
  const consentErr = consentRow ? consentRow.querySelector('.field-error') : null;
  if (!consent) {
    if (consentRow && !consentErr) {
      const err = document.createElement('span');
      err.className = 'field-error';
      err.textContent = 'Please give consent to proceed';
      consentRow.appendChild(err);
    }
    valid = false;
  } else {
    if (consentErr) consentErr.remove();
  }

  document.getElementById('start-btn').disabled = !valid;
  return valid;
}

// ── Session phases ────────────────────────────────────────────

/** Phase 1: validate form → populate reading screen → show it. */
function prepareSession() {
  if (!validateForm()) return;

  const name = document.getElementById('student-name').value.trim() || 'Student';
  const className = document.getElementById('class-name').value.trim() || '9';
  const section = document.getElementById('section-name').value.trim();
  const school = document.getElementById('school-name').value.trim();
  const age = Number(document.getElementById('student-age').value) || 15;
  const lang = document.getElementById('session-lang').value || 'hinglish';
  const caseStudyId = document.getElementById('case-study').value;
  const selectedCs = allCaseStudies.find(cs => cs.id === caseStudyId);

  // Always use English scenario for backend/Gemini
  const scenarioForBackend = selectedCs ? selectedCs.scenario_text : '';
  // Show language-appropriate text on reading screen
  const scenarioForDisplay = selectedCs ? getScenarioDisplay(selectedCs, lang) : '';

  state.sessionMeta = { name, className, section, school, age, lang,
    scenario: scenarioForBackend, caseStudyId, start: new Date() };

  // Populate reading screen
  document.getElementById('reading-scenario-text').textContent = scenarioForDisplay || 'No scenario loaded.';
  document.getElementById('reading-student-name').textContent = name;
  document.getElementById('reading-case-title').textContent = selectedCs ? selectedCs.title : '';

  showScreen('reading');
}

/** Phase 2: actually start media + Gemini session (called from reading screen). */
async function beginLiveSession() {
  const { name, scenario } = state.sessionMeta;

  // Reset session state
  state.recordedChunks = [];
  state.transcriptEntries = [];
  state.currentAiEntry = null;
  state.eventCount = 0;
  state.lastStudentTranscript = '';
  state.audioChunksPlayed = 0;
  state.savedSessionId = null;
  state.pendingTranscriptFlush = null;
  state.intentionalSessionEnd = false;
  state.geminiAudioCaptureDest = null;
  state.mixedRecordingCtx = null;
  state.mixedRecorder = null;
  state.mixedRecordedChunks = [];

  dom.transcriptEl.innerHTML = '';
  dom.enableAudioBtn.style.display = 'none';
  dom.aiAudio.srcObject = null;

  showScreen('live');
  setStatus('Connecting...');
  setDebug('Gemini: connecting');
  if (dom.caseStudyText) dom.caseStudyText.textContent = scenario || 'No case study loaded.';

  const hasVideoTrack = await setupMedia();
  setupRecorder(hasVideoTrack);

  await startGeminiSession(name, scenario);

  state.timerStart = Date.now();
  state.timerHandle = setInterval(() => {
    dom.timerEl.textContent = formatTime(Date.now() - state.timerStart);
  }, 500);
  setStatus('Listening...');
  updateDebugSnapshot();
}

// ── Event listeners ───────────────────────────────────────────

document.getElementById('start-btn').addEventListener('click', () => {
  prepareSession();
});

document.getElementById('ready-btn').addEventListener('click', () => {
  beginLiveSession().catch(err => { showToast(err.message); showScreen('welcome'); });
});

document.getElementById('back-btn').addEventListener('click', () => {
  showScreen('welcome');
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
    uiLog('INFO', state.isMuted ? 'Microphone muted' : 'Microphone unmuted');
  });
}

// Validation listeners — update button state on input, show errors only on blur
['student-name', 'school-name'].forEach(id => {
  const el = document.getElementById(id);
  if (!el) return;
  el.addEventListener('input', () => { clearFieldError(id); checkValidity(); });
  el.addEventListener('blur', () => {
    if (!el.value.trim()) showFieldError(id, id === 'student-name' ? 'Please enter your name' : 'Please enter your school name');
    checkValidity();
  });
});
document.getElementById('case-study').addEventListener('change', () => { clearFieldError('case-study'); checkValidity(); });
document.getElementById('consent-cb').addEventListener('change', () => {
  const consentRow = document.getElementById('consent-row');
  const consentErr = consentRow ? consentRow.querySelector('.field-error') : null;
  if (consentErr) consentErr.remove();
  checkValidity();
});

// Class + language change → re-filter case studies
document.getElementById('class-name').addEventListener('change', filterAndPopulateCaseStudies);
document.getElementById('session-lang').addEventListener('change', filterAndPopulateCaseStudies);

// Update case study preview on dropdown change
document.getElementById('case-study').addEventListener('change', () => {
  const lang = document.getElementById('session-lang').value;
  const id = document.getElementById('case-study').value;
  const cs = allCaseStudies.find(c => c.id === id);
  if (cs && dom.caseStudyText) dom.caseStudyText.textContent = getScenarioDisplay(cs, lang);
});

// ── Load case studies on page load ───────────────────────────

(async () => {
  try {
    const r = await fetch('/api/case-studies');
    const d = await r.json();
    allCaseStudies = d.case_studies;
    filterAndPopulateCaseStudies();
  } catch {
    showToast('Failed to load case studies');
  }
})();
