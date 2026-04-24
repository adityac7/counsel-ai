/**
 * Shared mutable state and DOM refs for the live session.
 *
 * Pure data — no imports. All other modules import from here
 * instead of from app.js to avoid circular dependencies.
 */

// ============================================================
// STATE
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
  _lastAiEntry: null,
  _pendingAiText: '',  // buffers outputTranscription that arrives before its modelTurn
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

  // Mixed recording (counsellor mic + AI audio + video)
  geminiAudioCaptureDest: null,
  mixedRecordingCtx: null,
  mixedRecorder: null,
  mixedRecordedChunks: [],

  // Event tracking
  eventTypeCounts: {},

  // Mute state
  isMuted: false,
};

export default state;

// ============================================================
// DOM REFS
// ============================================================

export const dom = {
  statusText: document.getElementById('status-text'),
  statusDot: document.getElementById('status-dot'),
  timerEl: document.getElementById('timer'),
  transcriptEl: document.getElementById('transcript'),
  preview: document.getElementById('preview'),
  previewWrap: document.getElementById('preview-wrap'),
  aiAudio: document.getElementById('ai-audio'),
  enableAudioBtn: document.getElementById('enable-audio-btn'),
  rtcDebug: document.getElementById('rtc-debug'),
  toast: document.getElementById('toast'),
  caseStudyText: document.getElementById('case-study-text'),
  counsellorSpeech: document.getElementById('counsellor-speech'),
  counsellorSpeechText: document.getElementById('counsellor-speech-text'),
};

// ============================================================
// SCREENS
// ============================================================

const screens = {
  welcome: document.getElementById('welcome'),
  reading: document.getElementById('reading'),
  live: document.getElementById('live'),
  summary: document.getElementById('summary'),
};

export function showScreen(name) {
  Object.values(screens).forEach(s => s.classList.add('hidden'));
  if (screens[name]) screens[name].classList.remove('hidden');
}

// Expose showScreen globally for tests
window.showScreen = showScreen;
