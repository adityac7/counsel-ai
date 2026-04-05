/**
 * Gemini Live WebSocket session — connection, message handling, audio playback.
 * Also includes transcript handling (merged from transcript.js).
 *
 * Consolidates: gemini-session.js + transcript.js
 * All previously-exported symbols are re-exported.
 */
import state from './app.js';
import { dom, setConnectionState, setStatus, showToast, setDebug, uiLog, updateDebugSnapshot } from './app.js';
import { endSession } from './analysis.js';

// ============================================================
// TRANSCRIPT — add entries, accumulate student chunks, extract
// ============================================================

export function addStudentTranscript(text, source) {
  const raw = typeof text === 'string' ? text : String(text ?? '');
  const clean = raw.trim();
  if (!clean) return false;
  if (clean === state.lastStudentTranscript) return false;
  state.lastStudentTranscript = clean;

  if (!state.currentStudentEntry) {
    state.currentStudentEntry = addEntry('student', clean);
  } else {
    const existing = state.currentStudentEntry.body.textContent;
    if (existing && !existing.endsWith(' ') && !clean.startsWith(' ')) {
      state.currentStudentEntry.body.textContent += ' ';
    }
    state.currentStudentEntry.body.textContent += clean;
    state.currentStudentEntry.data.text = state.currentStudentEntry.body.textContent;
    dom.transcriptEl.scrollTop = dom.transcriptEl.scrollHeight;
  }

  if (state.studentTranscriptTimer) clearTimeout(state.studentTranscriptTimer);
  state.studentTranscriptTimer = setTimeout(() => { state.currentStudentEntry = null; }, 1500);

  state.waitingForStudentTranscript = false;
  return true;
}

export function addEntry(role, text) {
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
  const data = { role: role === 'ai' ? 'counsellor' : 'student', text: text || '' };
  state.transcriptEntries.push(data);
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
  const now = state.geminiPlaybackCtx.currentTime;
  const startAt = Math.max(now, state.geminiPlaybackTime);
  source.start(startAt);
  state.geminiPlaybackTime = startAt + buffer.duration;
  state.audioChunksPlayed++;
  if (state.audioChunksPlayed === 1) uiLog('OK', `First audio chunk queued (${int16.length} samples)`);
  if (state.audioChunksPlayed % 50 === 0) uiLog('INFO', state.audioChunksPlayed + ' audio chunks played');
}

// Transcription is now handled natively by Gemini Live's input_audio_transcription.
// No polling needed — transcription events arrive via serverContent.inputTranscription.
export async function flushPendingStudentTranscript() {
  // No-op: native transcription doesn't buffer client-side.
  return '';
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
      // Show/hide "Student is speaking..." indicator
      const indicator = document.getElementById('speaking-indicator');
      if (indicator) {
        if (msg.isSpeech) {
          indicator.style.display = 'block';
          if (state._speakingTimeout) clearTimeout(state._speakingTimeout);
          state._speakingTimeout = setTimeout(() => { indicator.style.display = 'none'; }, 1500);
        }
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
      endSession();
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
      uiLog('OK', 'Session saved: ' + msg.session_id);
      return;
    }
    if (msg.type === 'go_away') {
      state.geminiReconnecting = true;
      setConnectionState('RECONNECTING');
      setStatus('Reconnecting...');
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
    dom.orb.classList.add('speaking');
    setStatus('Speaking...');
    for (const part of serverContent.modelTurn.parts) {
      if (part.inlineData && part.inlineData.data) playGeminiAudio(part.inlineData.data);
      if (part.text) {
        if (!state.currentAiEntry) state.currentAiEntry = addEntry('ai', '');
        state.currentAiEntry.body.textContent += part.text;
        state.currentAiEntry.data.text = state.currentAiEntry.body.textContent;
        dom.transcriptEl.scrollTop = dom.transcriptEl.scrollHeight;
      }
    }
  }

  if (serverContent.turnComplete) {
    dom.orb.classList.remove('speaking');
    if (state.currentAiEntry) state.currentAiEntry = null;
    state.currentStudentEntry = null;
    setStatus('Listening...');
  }

  // Student input transcription — native Gemini Live transcription
  if (serverContent.inputTranscription && serverContent.inputTranscription.text) {
    const txt = serverContent.inputTranscription.text.trim();
    if (txt) {
      addStudentTranscript(txt, 'gemini:native');
    }
  }

  // Output transcription (counsellor)
  if (serverContent.outputTranscription && serverContent.outputTranscription.text) {
    const txt = serverContent.outputTranscription.text.trim();
    if (txt) {
      if (!state.currentAiEntry) state.currentAiEntry = addEntry('ai', '');
      const existing = state.currentAiEntry.body.textContent;
      if (existing && !existing.endsWith(' ') && !txt.startsWith(' ')) {
        state.currentAiEntry.body.textContent += ' ';
      }
      state.currentAiEntry.body.textContent += txt;
      state.currentAiEntry.data.text = state.currentAiEntry.body.textContent;
      dom.transcriptEl.scrollTop = dom.transcriptEl.scrollHeight;
    }
  }
}

// ============================================================
// START GEMINI SESSION
// ============================================================

export async function startGeminiSession(name, scenario) {
  uiLog('INFO', 'Starting Gemini Live session...');
  state.geminiAudioCtx = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 16000 });
  const micSource = state.geminiAudioCtx.createMediaStreamSource(state.mediaStream);
  const bufferSize = 4096;
  state.geminiMicProcessor = state.geminiAudioCtx.createScriptProcessor(bufferSize, 1, 1);

  if (!state.geminiPlaybackCtx) {
    state.geminiPlaybackCtx = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 24000 });
    state.geminiPlaybackCtx.resume();
    state.geminiPlaybackTime = 0;
  }

  const wsProto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  const wsLang = state.sessionMeta.lang || 'hinglish';
  const wsUrl = `${wsProto}//${location.host}/api/gemini-ws?scenario=${encodeURIComponent(scenario)}&name=${encodeURIComponent(name)}&lang=${encodeURIComponent(wsLang)}&grade=${encodeURIComponent(state.sessionMeta.className || '')}&section=${encodeURIComponent(state.sessionMeta.section || '')}&school=${encodeURIComponent(state.sessionMeta.school || '')}&age=${encodeURIComponent(String(state.sessionMeta.age || 15))}`;
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
      if (!state.geminiWs || state.geminiWs.readyState !== WebSocket.OPEN) return;
      if (dom.preview.videoWidth === 0) return;
      captureCanvas.width = Math.min(dom.preview.videoWidth, 640);
      captureCanvas.height = Math.round(captureCanvas.width * (dom.preview.videoHeight / dom.preview.videoWidth));
      captureCtx.drawImage(dom.preview, 0, 0, captureCanvas.width, captureCanvas.height);
      const dataUrl = captureCanvas.toDataURL('image/jpeg', 0.6);
      const b64 = dataUrl.split(',')[1];
      state.geminiWs.send(JSON.stringify({ realtimeInput: { mediaChunks: [{ data: b64, mimeType: 'image/jpeg' }] } }));
    }, 10000); // 1 frame per 10s — reduces token usage, avoids 2-min A/V limit
  }

  setDebug('Gemini: connected | Mic: active' + (hasVideo ? ' | Cam: active' : ''));
}
