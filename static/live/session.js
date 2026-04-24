/**
 * Gemini Live WebSocket session — connection, message handling, audio playback.
 * Also includes transcript handling (merged from transcript.js).
 *
 * Consolidates: gemini-session.js + transcript.js
 * All previously-exported symbols are re-exported.
 */
import state from './state.js';
import { dom } from './state.js';
import { setConnectionState, setStatus, showToast, setDebug, uiLog, updateDebugSnapshot } from './app.js';

// ============================================================
// LIVE STATUS PANEL — speaker pills, session timer, mic waveform
// Replaces the on-screen transcript display. Transcript entries
// are still accumulated into state.transcriptEntries for the
// end-of-session analysis payload, they're just no longer shown
// to the student mid-session.
// ============================================================

const liveStatus = {
  pillStudent: document.getElementById('pill-student'),
  pillAi:      document.getElementById('pill-ai'),
  sessionTimer:document.getElementById('session-timer'),
  waveform:    document.getElementById('mic-waveform'),
  waveformCtx: null,
  bars:        new Array(50).fill(0),
  speakerClearTimer: null,
};
if (liveStatus.waveform && liveStatus.waveform.getContext) {
  liveStatus.waveformCtx = liveStatus.waveform.getContext('2d');
}

function setActiveSpeaker(who) {
  // who: 'student' | 'ai' | null
  if (liveStatus.pillStudent) liveStatus.pillStudent.classList.toggle('active', who === 'student');
  if (liveStatus.pillAi)      liveStatus.pillAi.classList.toggle('active', who === 'ai');
  state.aiSpeaking = who === 'ai';
}

function pad2(n) { return String(n).padStart(2, '0'); }
function formatMmSs(ms) {
  const s = Math.max(0, Math.floor(ms / 1000));
  return `${pad2(Math.floor(s / 60))}:${pad2(s % 60)}`;
}
function tickSessionTimer() {
  if (!liveStatus.sessionTimer) return;
  if (!state.timerStart) return;
  liveStatus.sessionTimer.textContent = formatMmSs(Date.now() - state.timerStart);
}
// Piggy-back on app.js's existing 500ms interval via rAF fallback: if the
// element exists, run our own lightweight interval so the new display
// updates even if app.js's #timer tick hasn't been adapted.
if (liveStatus.sessionTimer) {
  setInterval(tickSessionTimer, 500);
}

function drawWaveform() {
  const ctx = liveStatus.waveformCtx;
  const cvs = liveStatus.waveform;
  if (!ctx || !cvs) return;
  const w = cvs.width, h = cvs.height;
  ctx.clearRect(0, 0, w, h);
  const n = liveStatus.bars.length;
  const gap = 2;
  const barW = Math.max(1, Math.floor((w - gap * (n - 1)) / n));
  for (let i = 0; i < n; i++) {
    const v = Math.min(1, liveStatus.bars[i]);
    const bh = Math.max(2, Math.round(v * (h - 4)));
    const x  = i * (barW + gap);
    const y  = Math.round((h - bh) / 2);
    // Gradient-like flat fill using indigo; brightens with amplitude.
    const alpha = 0.35 + 0.65 * v;
    ctx.fillStyle = `rgba(99, 102, 241, ${alpha.toFixed(3)})`;
    ctx.fillRect(x, y, barW, bh);
  }
}

function pushWaveformSample(rmsInt16) {
  // rmsInt16 is int16-scaled (server sends round(rms*32768)). Normalize.
  // Typical speech lands roughly in 400–6000 range; use soft ceiling.
  const normalized = Math.min(1, Math.max(0, rmsInt16 / 4000));
  liveStatus.bars.push(normalized);
  if (liveStatus.bars.length > 50) liveStatus.bars.shift();
  drawWaveform();
}

// ============================================================
// TRANSCRIPT — add entries, accumulate student chunks, extract
// ============================================================

export function addStudentTranscript(text, source) {
  const raw = typeof text === 'string' ? text : String(text ?? '');
  if (!raw || !raw.trim()) return false;
  // Only dedup consecutive speech within the same turn (currentStudentEntry is non-null).
  // Once the turn ends (currentStudentEntry resets to null), allow identical text from new turns.
  if (state.currentStudentEntry && raw === state.lastStudentTranscript) return false;
  state.lastStudentTranscript = raw;

  if (!state.currentStudentEntry) {
    // First chunk — strip leading whitespace so the entry doesn't start
    // with a stray space. Interior chunks are kept verbatim.
    state.currentStudentEntry = addEntry('student', raw.replace(/^\s+/, ''));
  } else if (state.currentStudentEntry.body) {
    // Append raw — Gemini's chunks carry their own spacing:
    //   " I" (leading space = new word)  vs  "t" (no space = sub-word)
    // Trimming or inserting spaces here breaks sub-word fragments
    // ("not" → "no t", "able" → "a ble").
    state.currentStudentEntry.body.textContent += raw;
    state.currentStudentEntry.data.text = state.currentStudentEntry.body.textContent;
    if (dom.transcriptEl) dom.transcriptEl.scrollTop = dom.transcriptEl.scrollHeight;
  } else {
    // Transcript DOM not present — still track text on the data entry so
    // state.transcriptEntries stays correct for end-of-session analysis.
    state.currentStudentEntry.data.text = (state.currentStudentEntry.data.text || '') + raw;
  }

  if (state.studentTranscriptTimer) clearTimeout(state.studentTranscriptTimer);
  state.studentTranscriptTimer = setTimeout(() => { state.currentStudentEntry = null; state.lastStudentTranscript = ''; }, 3000);

  state.waitingForStudentTranscript = false;
  return true;
}

export function addEntry(role, text) {
  // Transcript display is disabled in live UI (see live-status panel).
  // We still push a `data` record into state.transcriptEntries so the
  // end-of-session analysis pipeline receives the full conversation.
  // If the hidden #transcript element exists, we also append a DOM
  // node so anything inspecting innerHTML / .entry nodes keeps working.
  const data = { role: role === 'ai' ? 'counsellor' : 'student', text: text || '' };
  state.transcriptEntries.push(data);

  if (!dom.transcriptEl) {
    return { body: null, data };
  }

  const entry = document.createElement('div');
  entry.className = `entry ${role === 'ai' ? 'ai' : ''}`;
  entry.dataset.role = role;
  const tag = document.createElement('div');
  tag.className = 'tag';
  tag.textContent = role === 'ai' ? 'Counsellor' : 'Student';
  const body = document.createElement('div');
  body.className = 'body';
  body.textContent = text;
  entry.append(tag, body);
  dom.transcriptEl.append(entry);
  dom.transcriptEl.scrollTop = dom.transcriptEl.scrollHeight;
  return { body, data };
}

export function collectTranscriptCandidates(value, path = 'msg', out = []) {
  if (!value) return out;
  if (typeof value === 'string') return out;
  if (Array.isArray(value)) {
    value.forEach((item, i) => collectTranscriptCandidates(item, `${path}[${i}]`, out));
    return out;
  }
  if (typeof value !== 'object') return out;
  if (typeof value.transcript === 'string') out.push({ text: value.transcript, source: `${path}.transcript` });
  if (typeof value.text === 'string' && /input_audio|user|conversation\.item|audio_transcription/.test(path)) {
    out.push({ text: value.text, source: `${path}.text` });
  }
  if (typeof value.delta === 'string' && /audio_transcription/.test(path)) {
    out.push({ text: value.delta, source: `${path}.delta` });
  }
  Object.keys(value).forEach(key => {
    collectTranscriptCandidates(value[key], `${path}.${key}`, out);
  });
  return out;
}

export function captureUserTranscriptFromMessage(msg, contextType) {
  const role = msg?.role || msg?.item?.role || msg?.content_part?.role || msg?.item?.author?.role || '';
  const isUserScoped = role === 'user' || state.waitingForStudentTranscript || /input_audio|audio_transcription|user/.test(contextType || '');
  if (!isUserScoped) return;
  const candidates = collectTranscriptCandidates(msg);
  let captured = false;
  for (const candidate of candidates) {
    const didCapture = addStudentTranscript(candidate.text, `${contextType || 'event'}:${candidate.source}`);
    captured = didCapture || captured;
  }
  if (!captured) { uiLog('WARN', 'No student transcript text found for event:', contextType); }
}

// ============================================================
// AUDIO HELPERS
// ============================================================

export function arrayBufferToBase64(buffer) {
  const bytes = new Uint8Array(buffer);
  let binary = '';
  for (let i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i]);
  return btoa(binary);
}

function base64ToInt16Array(base64) {
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return new Int16Array(bytes.buffer);
}

export function playGeminiAudio(base64Data) {
  if (state.intentionalSessionEnd) return;
  if (!state.geminiPlaybackCtx) { uiLog('ERR', '[audio] No playback context!'); return; }
  if (state.geminiPlaybackCtx.state !== 'running') {
    state.geminiPlaybackCtx.resume().catch(e => uiLog('ERR', '[audio] Resume failed: ' + e.message));
  }
  const int16 = base64ToInt16Array(base64Data);
  if (int16.length === 0) return;
  if (state.audioChunksPlayed === 0) {
    const maxVal = int16.reduce((m, v) => Math.max(m, Math.abs(v)), 0);
    uiLog('INFO', `[audio-debug] ctx.state=${state.geminiPlaybackCtx.state} sampleRate=${state.geminiPlaybackCtx.sampleRate} samples=${int16.length} maxAmplitude=${maxVal}`);
  }
  const float32 = new Float32Array(int16.length);
  for (let i = 0; i < int16.length; i++) float32[i] = int16[i] / 32768.0;
  const buffer = state.geminiPlaybackCtx.createBuffer(1, float32.length, 24000);
  buffer.getChannelData(0).set(float32);
  const source = state.geminiPlaybackCtx.createBufferSource();
  source.buffer = buffer;
  source.connect(state.geminiPlaybackCtx.destination);
  if (state.geminiAudioCaptureDest) source.connect(state.geminiAudioCaptureDest);
  const now = state.geminiPlaybackCtx.currentTime;
  const startAt = Math.max(now, state.geminiPlaybackTime);
  source.start(startAt);
  state.geminiPlaybackTime = startAt + buffer.duration;
  state.audioChunksPlayed++;
  if (state.audioChunksPlayed === 1) uiLog('OK', `First audio chunk queued (${int16.length} samples)`);
  if (state.audioChunksPlayed % 50 === 0) uiLog('INFO', state.audioChunksPlayed + ' audio chunks played');
}

// ============================================================
// SESSION SAVED HANDSHAKE — resolves when server confirms save
// ============================================================

let _sessionSavedResolve = null;

/**
 * Returns a promise that resolves when the server sends a `session_saved`
 * message. If the message doesn't arrive within `timeoutMs`, the promise
 * resolves anyway so analysis can proceed with whatever session_id we have.
 */
export function waitForSessionSaved(timeoutMs = 5000) {
  return new Promise(resolve => {
    // Already received before we started waiting
    if (state.savedSessionId && state.pendingTranscriptFlush === 'done') {
      resolve(state.savedSessionId);
      return;
    }
    _sessionSavedResolve = resolve;
    setTimeout(() => {
      if (_sessionSavedResolve) {
        _sessionSavedResolve = null;
        resolve(state.savedSessionId);
      }
    }, timeoutMs);
  });
}

// ============================================================
// GEMINI MESSAGE HANDLER
// ============================================================

export function handleGeminiMessage(msg) {
  state.eventCount++;
  updateDebugSnapshot();

  const serverContent = msg.serverContent;
  if (!serverContent) {
    if (msg.type === 'keepalive') return;
    if (msg.type === 'audioLevel') {
      // Drive mic waveform from every audioLevel tick.
      if (typeof msg.rms === 'number') pushWaveformSample(msg.rms);

      // Light the Student pill while speech is detected — don't clobber the
      // AI pill if the AI is currently speaking (modelTurn audio sets that).
      if (msg.isSpeech && !state.aiSpeaking) {
        setActiveSpeaker('student');
        if (liveStatus.speakerClearTimer) clearTimeout(liveStatus.speakerClearTimer);
        liveStatus.speakerClearTimer = setTimeout(() => {
          if (!state.aiSpeaking) setActiveSpeaker(null);
        }, 1200);
      }
      return;
    }
    if (msg.type === 'reconnecting') {
      state.geminiReconnecting = true;
      setConnectionState('RECONNECTING');
      setStatus(`Reconnecting (${msg.attempt}/${msg.maxAttempts})...`);
      return;
    }
    if (msg.type === 'connection_active') {
      state.geminiReconnecting = false;
      setConnectionState('ACTIVE');
      setStatus('Listening...');
      return;
    }
    if (msg.type === 'setup_complete') {
      setConnectionState('INITIALIZING');
      return;
    }
    if (msg.type === 'wrapup_warning') {
      const secs = msg.remaining_seconds || 90;
      uiLog('WARN', `Wrapup warning: ${secs}s remaining`);
      dom.timerEl.style.color = 'var(--warning)';
      dom.timerEl.style.borderColor = 'var(--warning)';
      showToast(`Wrapping up in ~${Math.ceil(secs / 60)} minute`);
      return;
    }
    if (msg.type === 'session_timeout') {
      uiLog('WARN', 'Session timed out by server');
      window.dispatchEvent(new CustomEvent('counselai:session_timeout'));
      return;
    }
    if (msg.type === 'reconnected') {
      state.geminiReconnecting = false;
      setConnectionState('ACTIVE');
      setStatus('Listening...');
      return;
    }
    if (msg.type === 'session_started') {
      state.savedSessionId = msg.session_id;
      if (msg.started_at) state.sessionMeta.serverStartedAt = msg.started_at;
      uiLog('OK', 'Session started: ' + msg.session_id);
      return;
    }
    if (msg.type === 'session_saved') {
      state.savedSessionId = msg.session_id;
      state.pendingTranscriptFlush = 'done';
      uiLog('OK', 'Session saved: ' + msg.session_id);
      if (_sessionSavedResolve) {
        const resolve = _sessionSavedResolve;
        _sessionSavedResolve = null;
        resolve(msg.session_id);
      }
      return;
    }
    if (msg.type === 'go_away') {
      state.geminiReconnecting = true;
      setConnectionState('RECONNECTING');
      setStatus('Reconnecting...');
      return;
    }
    if (msg.type === 'ai_speaking') {
      // Server-authoritative signal that Gemini is producing TTS audio.
      // Client gates outbound video frames on this flag — no point sending
      // frames while the counsellor is talking.
      state.aiSpeaking = !!msg.state;
      return;
    }
    if (msg.type === 'error') {
      setConnectionState('ERROR');
      if (msg.reconnect_failed) {
        const saved = msg.turns_saved || 0;
        showToast(`Connection lost. ${saved} turns saved. Click End session to see analysis.`);
      } else if (msg.reconnect !== true) {
        showToast(msg.message || 'Gemini error');
      }
      return;
    }
    return;
  }

  // Model audio/text output
  if (serverContent.modelTurn && serverContent.modelTurn.parts) {
    setStatus('Speaking...');
    state._lastAiEntry = null;

    // Create AI entry immediately — audio-native models send audio first,
    // text arrives later via outputTranscription.
    // Apply any buffered transcription that arrived before this modelTurn.
    if (!state.currentAiEntry) {
      state.currentAiEntry = addEntry('ai', state._pendingAiText);
      if (state._pendingAiText) {
        if (state.currentAiEntry.body) state.currentAiEntry.body.textContent = state._pendingAiText;
        state._pendingAiText = '';
      }
      // Reset the visible counsellor speech panel at the start of each new turn,
      // but keep any pending text that was already buffered and applied above.
      if (dom.counsellorSpeechText && !state.currentAiEntry.data.text) {
        dom.counsellorSpeechText.textContent = '';
      }
    }

    let hasAudio = false;
    for (const part of serverContent.modelTurn.parts) {
      if (part.inlineData && part.inlineData.data) {
        playGeminiAudio(part.inlineData.data);
        hasAudio = true;
      }
      if (part.text && state.currentAiEntry && state.currentAiEntry.body) {
        state.currentAiEntry.body.textContent += part.text;
        state.currentAiEntry.data.text = state.currentAiEntry.body.textContent;
        if (dom.transcriptEl) dom.transcriptEl.scrollTop = dom.transcriptEl.scrollHeight;
      } else if (part.text && state.currentAiEntry) {
        state.currentAiEntry.data.text = (state.currentAiEntry.data.text || '') + part.text;
      }
    }

    // AI is speaking — light the Counsellor pill (and mark state.aiSpeaking
    // so Stream B can gate outbound video frames).
    if (hasAudio) setActiveSpeaker('ai');
  }

  if (serverContent.turnComplete) {
    if (state.currentAiEntry) {
      state._lastAiEntry = state.currentAiEntry;
      state.currentAiEntry = null;
    } else {
      // Student turn completed — clear _lastAiEntry so outputTranscription
      // for the upcoming counsellor turn doesn't append to the old AI entry.
      state._lastAiEntry = null;
    }
    state.currentStudentEntry = null;
    state.lastStudentTranscript = '';
    setActiveSpeaker(null);
    setStatus('Listening...');
  }

  // Student input transcription — native Gemini Live transcription
  if (serverContent.inputTranscription && serverContent.inputTranscription.text) {
    // Keep the raw text (including leading spaces — Gemini uses them as word
    // separators between sub-word chunks). addStudentTranscript already strips
    // leading whitespace for the first chunk only.
    const txt = serverContent.inputTranscription.text;
    if (txt && txt.trim()) {
      addStudentTranscript(txt, 'gemini:native');
    }
  }

  // Output transcription (counsellor) — streamed delta chunks from Gemini.
  // Append raw (Gemini's chunks carry their own spacing). We keep the hidden
  // transcript entry up-to-date for end-of-session analysis AND mirror the
  // running text into the visible counsellor-speech panel so the student can
  // read what was said if they mishear.
  if (serverContent.outputTranscription && serverContent.outputTranscription.text) {
    const raw = serverContent.outputTranscription.text;
    if (raw && raw.trim()) {
      const target = state.currentAiEntry || state._lastAiEntry;
      if (target) {
        if (target.body) {
          target.body.textContent += raw;
          target.data.text = target.body.textContent;
        } else {
          target.data.text = (target.data.text || '') + raw;
        }
      } else {
        // outputTranscription arrived before the next modelTurn — buffer it.
        // modelTurn handler will prepend this to the new entry when it fires.
        state._pendingAiText = (state._pendingAiText || '') + raw;
      }
      if (dom.counsellorSpeechText) {
        dom.counsellorSpeechText.textContent = (dom.counsellorSpeechText.textContent || '') + raw;
      }
      if (dom.transcriptEl) dom.transcriptEl.scrollTop = dom.transcriptEl.scrollHeight;
    }
  }
}

// ============================================================
// START GEMINI SESSION
// ============================================================

export async function startGeminiSession(name, scenario) {
  uiLog('INFO', 'Starting Gemini Live session...');
  if (!state.mediaStream || !(state.mediaStream instanceof MediaStream)) {
    throw new Error('Microphone not available — please allow mic access and try again.');
  }

  // Create playback context first (24kHz for Gemini audio output)
  if (!state.geminiPlaybackCtx) {
    state.geminiPlaybackCtx = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 24000 });
    state.geminiPlaybackCtx.resume().then(() => uiLog('OK', 'Playback AudioContext resumed'));
    state.geminiPlaybackTime = 0;
  }

  // Tap AI audio output so we can mix it into the local recording
  state.geminiAudioCaptureDest = state.geminiPlaybackCtx.createMediaStreamDestination();

  // Create mic capture context (16kHz for Gemini audio input)
  state.geminiAudioCtx = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 16000 });
  const micSource = state.geminiAudioCtx.createMediaStreamSource(state.mediaStream);
  const bufferSize = 512;
  state.geminiMicProcessor = state.geminiAudioCtx.createScriptProcessor(bufferSize, 1, 1);

  const wsProto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  const wsLang = state.sessionMeta.lang || 'hinglish';
  const wsUrl = `${wsProto}//${location.host}/api/gemini-ws?scenario=${encodeURIComponent(scenario)}&name=${encodeURIComponent(name)}&lang=${encodeURIComponent(wsLang)}&grade=${encodeURIComponent(state.sessionMeta.className || '')}&section=${encodeURIComponent(state.sessionMeta.section || '')}&school=${encodeURIComponent(state.sessionMeta.school || '')}&age=${encodeURIComponent(String(state.sessionMeta.age || 15))}&case_study_id=${encodeURIComponent(state.sessionMeta.caseStudyId || '')}`;
  state.geminiWs = new WebSocket(wsUrl);
  setConnectionState('CONNECTING');

  await new Promise((resolve, reject) => {
    const timeout = setTimeout(() => reject(new Error('Gemini WebSocket connection timed out (30s)')), 30000);
    state.geminiWs.onopen = () => { uiLog('OK', 'WebSocket connected to server'); };
    state.geminiWs.onmessage = (ev) => {
      let msg;
      try { msg = JSON.parse(ev.data); } catch { return; }
      if (msg.type === 'setup_complete') { clearTimeout(timeout); setConnectionState('INITIALIZING'); setStatus('Connected'); resolve(); return; }
      if (msg.type === 'error') { clearTimeout(timeout); setConnectionState('ERROR'); reject(new Error(msg.message || 'Gemini error')); return; }
      handleGeminiMessage(msg);
    };
    state.geminiWs.onerror = () => { clearTimeout(timeout); setConnectionState('ERROR'); reject(new Error('Gemini WebSocket error')); };
    state.geminiWs.onclose = (ev) => {
      const code = ev.code || 0;
      const codeLabels = { 1000: 'Normal', 1001: 'Going away', 1006: 'Abnormal (no close frame)', 1011: 'Server error' };
      uiLog('WARN', `WebSocket closed: ${codeLabels[code] || 'code ' + code}`);
      setConnectionState('CLOSED');
      if (!state.intentionalSessionEnd && !state.geminiReconnecting && code !== 1000) {
        setStatus('Disconnected');
        showToast('Connection lost. Your conversation has been saved. Click End session to see analysis.');
      }
    };
  });

  state.geminiWs.onmessage = (ev) => {
    let msg;
    try { msg = JSON.parse(ev.data); } catch { return; }
    handleGeminiMessage(msg);
  };

  // Mic processor — stream audio to Gemini (respects mute state)
  state.geminiMicProcessor.onaudioprocess = (e) => {
    if (!state.geminiWs || state.geminiWs.readyState !== WebSocket.OPEN) return;
    // When muted, stop sending audio entirely (save tokens, reduce noise)
    if (state.isMuted) return;
    const float32 = e.inputBuffer.getChannelData(0);
    const int16 = new Int16Array(float32.length);
    for (let i = 0; i < float32.length; i++) {
      int16[i] = Math.max(-32768, Math.min(32767, Math.round(float32[i] * 32767)));
    }
    const base64 = arrayBufferToBase64(int16.buffer);
    state.geminiWs.send(JSON.stringify({ realtimeInput: { mediaChunks: [{ data: base64, mimeType: 'audio/pcm;rate=16000' }] } }));
  };

  micSource.connect(state.geminiMicProcessor);
  state.geminiMicProcessor.connect(state.geminiAudioCtx.destination);
  uiLog('OK', 'Mic capture active (16kHz PCM)');

  const hasVideo = state.mediaStream.getVideoTracks().length > 0;
  if (hasVideo) {
    const captureCanvas = document.createElement('canvas');
    const captureCtx = captureCanvas.getContext('2d');
    state.geminiVideoInterval = setInterval(() => {
      // Skip frame while AI is speaking — no need to burn vision tokens
      // while the counsellor is the one talking.
      if (state.aiSpeaking) return;
      if (!state.geminiWs || state.geminiWs.readyState !== WebSocket.OPEN) return;
      if (dom.preview.videoWidth === 0) return;
      captureCanvas.width = Math.min(dom.preview.videoWidth, 384);
      captureCanvas.height = Math.round(captureCanvas.width * (dom.preview.videoHeight / dom.preview.videoWidth));
      captureCtx.drawImage(dom.preview, 0, 0, captureCanvas.width, captureCanvas.height);
      const dataUrl = captureCanvas.toDataURL('image/jpeg', 0.6);
      const b64 = dataUrl.split(',')[1];
      state.geminiWs.send(JSON.stringify({ realtimeInput: { mediaChunks: [{ data: b64, mimeType: 'image/jpeg' }] } }));
    }, 10000); // 1 frame per 10s — reduces token usage, avoids 2-min A/V limit
  }

  // Start mixed recorder: counsellor video + mic + AI audio in one file
  try {
    state.mixedRecordingCtx = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 48000 });
    const mixDest = state.mixedRecordingCtx.createMediaStreamDestination();

    // Counsellor mic → mix
    const micMixSrc = state.mixedRecordingCtx.createMediaStreamSource(state.mediaStream);
    micMixSrc.connect(mixDest);

    // AI audio capture → mix
    const aiMixSrc = state.mixedRecordingCtx.createMediaStreamSource(state.geminiAudioCaptureDest.stream);
    aiMixSrc.connect(mixDest);

    // Combine counsellor video track(s) with the mixed audio track
    const videoTracks = state.mediaStream.getVideoTracks();
    const mixedStream = new MediaStream([...videoTracks, ...mixDest.stream.getAudioTracks()]);

    const mixMimeCandidates = videoTracks.length > 0
      ? ['video/webm;codecs=vp9,opus', 'video/webm;codecs=vp8,opus', 'video/webm']
      : ['audio/webm;codecs=opus', 'audio/webm'];
    const mixMime = mixMimeCandidates.find(t => MediaRecorder.isTypeSupported(t));

    state.mixedRecordedChunks = [];
    state.mixedRecorder = new MediaRecorder(mixedStream, mixMime ? { mimeType: mixMime } : {});
    state.mixedRecorder.ondataavailable = e => { if (e.data && e.data.size > 0) state.mixedRecordedChunks.push(e.data); };
    state.mixedRecorder.onerror = e => uiLog('WARN', '[mixed-rec] error: ' + e);
    state.mixedRecorder.start(1000);
    uiLog('OK', 'Mixed recorder started' + (mixMime ? ' (' + mixMime + ')' : ''));
  } catch (e) {
    uiLog('WARN', '[mixed-rec] Could not start mixed recorder: ' + e.message);
  }

  setDebug('Gemini: connected | Mic: active' + (hasVideo ? ' | Cam: active' : ''));
}
