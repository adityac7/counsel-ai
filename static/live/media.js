/**
 * Media capture and audio waveform visualizer.
 *
 * Consolidates: media-capture.js + waveform.js
 * All previously-exported symbols are re-exported.
 */
import state from './state.js';
import { dom } from './state.js';
import { uiLog, showToast, updateDebugSnapshot } from './app.js';

// ============================================================
// WAVEFORM — canvas-based frequency bars
// ============================================================

const waveCanvas = document.getElementById('waveform-canvas');
const waveCtx = waveCanvas.getContext('2d');
let waveAnimId = null;
let waveAnalyser = null;
let waveDataArray = null;

export function initWaveform(stream) {
  const actx = new (window.AudioContext || window.webkitAudioContext)();
  const source = actx.createMediaStreamSource(stream);
  waveAnalyser = actx.createAnalyser();
  waveAnalyser.fftSize = 256;
  waveAnalyser.smoothingTimeConstant = 0.8;
  source.connect(waveAnalyser);
  waveDataArray = new Uint8Array(waveAnalyser.frequencyBinCount);
  resizeWaveCanvas();
  drawWaveform();
}

function resizeWaveCanvas() {
  const rect = waveCanvas.getBoundingClientRect();
  waveCanvas.width = rect.width * window.devicePixelRatio;
  waveCanvas.height = rect.height * window.devicePixelRatio;
  waveCtx.scale(window.devicePixelRatio, window.devicePixelRatio);
}

function drawWaveform() {
  waveAnimId = requestAnimationFrame(drawWaveform);
  if (!waveAnalyser) return;
  waveAnalyser.getByteFrequencyData(waveDataArray);
  const w = waveCanvas.width / window.devicePixelRatio;
  const h = waveCanvas.height / window.devicePixelRatio;
  waveCtx.clearRect(0, 0, w, h);
  const bars = 48;
  const step = Math.floor(waveDataArray.length / bars);
  const barW = (w / bars) * 0.6;
  const gap = (w / bars) * 0.4;
  for (let i = 0; i < bars; i++) {
    const val = waveDataArray[i * step] / 255;
    const barH = Math.max(2, val * h * 0.85);
    const x = i * (barW + gap) + gap / 2;
    const y = (h - barH) / 2;
    const gradient = waveCtx.createLinearGradient(x, y, x, y + barH);
    gradient.addColorStop(0, 'rgba(45, 157, 143, 0.7)');
    gradient.addColorStop(1, 'rgba(212, 165, 67, 0.5)');
    waveCtx.fillStyle = gradient;
    waveCtx.beginPath();
    waveCtx.roundRect(x, y, barW, barH, 2);
    waveCtx.fill();
  }
}

window.addEventListener('resize', () => { if (waveAnalyser) resizeWaveCanvas(); });

export function stopWaveform() {
  if (waveAnimId) { cancelAnimationFrame(waveAnimId); waveAnimId = null; }
}

// ============================================================
// MEDIA CAPTURE — getUserMedia, MediaRecorder, pre-flight
// ============================================================

function buildRecordedBlob() {
  const mime = state.recorder?.mimeType || state.sessionMeta?.mediaStatus?.recorderMimeType || 'video/webm';
  const blob = state.recordedChunks.length ? new Blob(state.recordedChunks, { type: mime }) : null;
  if (state.sessionMeta?.mediaStatus) {
    const size = blob ? blob.size : 0;
    state.sessionMeta.mediaStatus.recordingSize = size;
    state.sessionMeta.mediaStatus.videoStatus = size > 0 ? 'captured' : 'missing';
  }
  return blob;
}

export async function setupMedia() {
  try {
    state.mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true, video: true });
  } catch {
    state.mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
  }
  if (!state.mediaStream.getAudioTracks().length) throw new Error('No microphone track available.');

  // Pre-flight: verify audio track is live
  const audioTrack = state.mediaStream.getAudioTracks()[0];
  if (audioTrack.readyState !== 'live') {
    showToast('Microphone track is not live. Check permissions.');
  }
  audioTrack.onended = () => {
    uiLog('ERR', 'Microphone disconnected');
    showToast('Microphone disconnected. End session to save transcript.');
  };
  state.sessionMeta.mediaStatus = {
    hasAudio: true,
    hasVideo: false,
    recorderStarted: false,
    recorderMimeType: '',
    dataEventCount: 0,
    chunkCount: 0,
    zeroByteChunkCount: 0,
    totalBytes: 0,
    recordingSize: 0,
    videoStatus: 'pending',
  };

  initWaveform(state.mediaStream);
  dom.preview.srcObject = state.mediaStream;

  const hasVideoTrack = state.mediaStream.getVideoTracks().length > 0;
  if (!hasVideoTrack) {
    dom.previewWrap.style.display = 'none';
  } else {
    dom.previewWrap.style.display = 'block';
    state.sessionMeta.mediaStatus.hasVideo = true;
  }

  return hasVideoTrack;
}

export function setupRecorder(hasVideoTrack) {
  const mimeCandidates = hasVideoTrack
    ? ['video/webm;codecs=vp9,opus', 'video/webm;codecs=vp8,opus', 'video/webm;codecs=opus', 'video/webm']
    : ['audio/webm;codecs=opus', 'audio/webm', 'video/webm;codecs=opus', 'video/webm'];
  const recorderOptions = {};
  const selectedMime = mimeCandidates.find(type => MediaRecorder.isTypeSupported(type));
  if (selectedMime) recorderOptions.mimeType = selectedMime;

  state.recorder = new MediaRecorder(state.mediaStream, recorderOptions);
  state.recorder.onstart = () => {
    if (state.sessionMeta.mediaStatus) {
      state.sessionMeta.mediaStatus.recorderStarted = true;
      state.sessionMeta.mediaStatus.recorderMimeType = state.recorder.mimeType || selectedMime || '';
    }
    updateDebugSnapshot();
  };
  state.recorder.onerror = e => console.error('[CounselAI] Recorder error:', e);
  state.recorder.ondataavailable = e => {
    if (state.sessionMeta.mediaStatus) {
      state.sessionMeta.mediaStatus.dataEventCount += 1;
      if (e.data && e.data.size > 0) state.recordedChunks.push(e.data);
      else state.sessionMeta.mediaStatus.zeroByteChunkCount += 1;
      state.sessionMeta.mediaStatus.chunkCount = state.recordedChunks.length;
      state.sessionMeta.mediaStatus.totalBytes = state.recordedChunks.reduce((sum, c) => sum + (c.size || 0), 0);
      state.sessionMeta.mediaStatus.videoStatus = state.sessionMeta.mediaStatus.totalBytes > 0 ? 'captured' : 'missing';
    } else if (e.data && e.data.size > 0) {
      state.recordedChunks.push(e.data);
    }
    updateDebugSnapshot();
  };
  state.recorder.onstop = () => updateDebugSnapshot();
  state.recorder.start(1000);
  updateDebugSnapshot();

  // Health check: warn if no chunks after 5s
  setTimeout(() => {
    if (state.sessionMeta?.mediaStatus?.chunkCount === 0) {
      uiLog('WARN', 'No recording chunks after 5s');
      showToast('Recording may not be working. Keep this tab in focus.');
    }
  }, 5000);
}

export function finalizeRecording() {
  return new Promise(resolve => {
    if (!state.recorder || state.recorder.state === 'inactive') return resolve(buildRecordedBlob());
    let resolved = false;
    const finish = () => {
      if (resolved) return;
      resolved = true;
      resolve(buildRecordedBlob());
    };
    try { state.recorder.requestData(); } catch {}
    const stopTimer = setTimeout(() => finish(), 3000);
    const previousOnStop = state.recorder.onstop;
    state.recorder.onstop = (event) => {
      clearTimeout(stopTimer);
      if (typeof previousOnStop === 'function') previousOnStop(event);
      finish();
    };
    state.recorder.stop();
  });
}

export function finalizeMixedRecording() {
  return new Promise(resolve => {
    const buildBlob = () => {
      if (!state.mixedRecordedChunks.length) return null;
      const mime = state.mixedRecorder?.mimeType || 'video/webm';
      return new Blob(state.mixedRecordedChunks, { type: mime });
    };
    if (!state.mixedRecorder || state.mixedRecorder.state === 'inactive') return resolve(buildBlob());
    let resolved = false;
    const finish = () => {
      if (resolved) return;
      resolved = true;
      resolve(buildBlob());
    };
    try { state.mixedRecorder.requestData(); } catch {}
    const timer = setTimeout(finish, 3000);
    state.mixedRecorder.onstop = () => { clearTimeout(timer); finish(); };
    state.mixedRecorder.stop();
  });
}
