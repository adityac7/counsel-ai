/**
 * Post-session analysis — endSession, profile rendering, summary display.
 */
import state from './state.js';
import { dom, showScreen } from './state.js';
import { setStatus, showToast, formatTime, uiLog } from './app.js';
import { stopWaveform, finalizeRecording } from './media.js';
import { waitForSessionSaved } from './session.js';

// Listen for session timeout events dispatched by session.js
window.addEventListener('counselai:session_timeout', () => endSession());

function renderSection(sectionEl, items) {
  sectionEl.innerHTML = '';
  if (!items.length) { sectionEl.textContent = 'No data returned.'; return; }
  const list = document.createElement('div');
  items.forEach(item => {
    const row = document.createElement('div');
    row.style.cssText = 'margin-bottom:8px;color:var(--text-soft);font-size:0.9rem;line-height:1.5;';
    row.textContent = item;
    list.appendChild(row);
  });
  sectionEl.appendChild(list);
}

function buildMetrics(profile) {
  dom.profileMetrics.innerHTML = '';
  const metrics = [
    { label: 'Critical Thinking', value: profile?.cognitive_profile?.critical_thinking },
    { label: 'Perspective Taking', value: profile?.cognitive_profile?.perspective_taking },
    { label: 'EQ Score', value: profile?.emotional_profile?.eq_score },
    { label: 'Confidence', value: profile?.behavioral_insights?.confidence },
  ].filter(m => m.value != null);
  if (!metrics.length) { dom.profileMetrics.textContent = 'No scores available.'; return; }
  metrics.forEach(m => {
    const card = document.createElement('div');
    card.style.cssText = 'display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;';
    const label = document.createElement('span');
    label.style.cssText = 'font-size:0.88rem;color:var(--text-soft);';
    label.textContent = m.label;
    const bar = document.createElement('div');
    bar.style.cssText = 'display:flex;align-items:center;gap:8px;';
    const track = document.createElement('div');
    track.style.cssText = 'width:100px;height:6px;background:rgba(0,0,0,0.06);border-radius:4px;overflow:hidden;';
    const fill = document.createElement('div');
    const pct = Math.min(100, (m.value / 10) * 100);
    fill.style.cssText = `height:100%;border-radius:4px;transition:width 1s ease;background:${pct >= 70 ? 'var(--success)' : pct >= 40 ? 'var(--warning)' : 'var(--danger)'};width:${pct}%;`;
    track.appendChild(fill);
    const num = document.createElement('strong');
    num.style.cssText = 'font-size:0.85rem;min-width:36px;text-align:right;';
    num.textContent = m.value + '/10';
    bar.append(track, num);
    card.append(label, bar);
    dom.profileMetrics.appendChild(card);
  });
}

function renderRecommendations(profile) {
  dom.recommendationsEl.innerHTML = '';
  const list = Array.isArray(profile?.recommendations) ? profile.recommendations : [];
  if (list.length === 0) { dom.recommendationsEl.textContent = 'No recommendations returned.'; return; }
  const ul = document.createElement('ul');
  ul.style.cssText = 'margin:0;padding-left:18px;color:var(--text-soft);';
  list.forEach(item => { const li = document.createElement('li'); li.style.marginBottom = '6px'; li.textContent = item; ul.appendChild(li); });
  dom.recommendationsEl.appendChild(ul);
}

function renderFaceAnalysis(faceData) {
  const el = document.getElementById('face-analysis-section');
  if (!faceData || (!faceData.dominant_emotion && !faceData.summary)) {
    el.textContent = 'No face data captured (camera may not have been available).';
    return;
  }
  // Support both new schema (flat) and legacy schema (nested under .summary)
  const s = faceData.summary || faceData;
  const items = [
    s.dominant_emotion ? 'Dominant emotion: ' + s.dominant_emotion : '',
    s.eye_contact_score != null ? 'Eye contact score: ' + s.eye_contact_score + '/10' : '',
    s.facial_tension_score != null ? 'Facial tension: ' + s.facial_tension_score + '/10' : '',
    s.emotion_stability ? 'Emotion stability: ' + s.emotion_stability : '',
    s.engagement_indicators ? 'Engagement: ' + s.engagement_indicators : '',
  ].filter(Boolean);
  if (Array.isArray(s.notable_expressions) && s.notable_expressions.length) {
    items.push('Notable expressions: ' + s.notable_expressions.join(', '));
  }
  if (Array.isArray(s.emotion_trajectory) && s.emotion_trajectory.length) {
    const traj = s.emotion_trajectory.map(t => t.point + ': ' + t.emotion).join(' → ');
    items.push('Emotion trajectory: ' + traj);
  }
  el.innerHTML = items.map(i => '<div style="margin-bottom:6px;">' + i + '</div>').join('');
}

function renderVoiceAnalysis(voiceData) {
  const el = document.getElementById('voice-analysis-section');
  if (!voiceData || (!voiceData.speech_patterns && !voiceData.speech_rate)) {
    el.textContent = 'No voice data captured.';
    return;
  }
  const items = [
    // New schema fields
    voiceData.speech_patterns ? 'Speech patterns: ' + voiceData.speech_patterns : '',
    voiceData.confidence_level ? 'Confidence level: ' + voiceData.confidence_level : '',
    voiceData.speech_rate && typeof voiceData.speech_rate === 'string' ? 'Speech rate: ' + voiceData.speech_rate : '',
    voiceData.volume_pattern ? 'Volume pattern: ' + voiceData.volume_pattern : '',
    voiceData.overall_confidence_score != null ? 'Voice confidence: ' + voiceData.overall_confidence_score + '/10' : '',
    // Legacy schema fields
    voiceData.speech_rate?.words_per_minute ? 'Speech rate: ' + voiceData.speech_rate.words_per_minute.toFixed(0) + ' WPM' : '',
    voiceData.volume?.pattern ? 'Volume pattern: ' + voiceData.volume.pattern : '',
  ].filter(Boolean);
  if (Array.isArray(voiceData.hesitation_markers) && voiceData.hesitation_markers.length) {
    items.push('Hesitation markers: ' + voiceData.hesitation_markers.join(', '));
  }
  if (Array.isArray(voiceData.emotional_tone_shifts) && voiceData.emotional_tone_shifts.length) {
    const shifts = voiceData.emotional_tone_shifts.map(s => s.point + ': ' + s.shift).join(' → ');
    items.push('Tone shifts: ' + shifts);
  }
  el.innerHTML = items.map(i => '<div style="margin-bottom:6px;">' + i + '</div>').join('');
}

function renderProfileSections(profile) {
  const traits = Array.isArray(profile?.personality_snapshot?.traits) ? profile.personality_snapshot.traits : [];
  renderSection(dom.personalitySection, [
    traits.length ? `Traits: ${traits.join(', ')}` : '',
    profile?.personality_snapshot?.communication_style ? `Communication style: ${profile.personality_snapshot.communication_style}` : '',
    profile?.personality_snapshot?.decision_making ? `Decision making: ${profile.personality_snapshot.decision_making}` : '',
  ].filter(Boolean));
  renderSection(dom.cognitiveSection, [
    profile?.cognitive_profile?.moral_reasoning_stage ? `Moral reasoning stage: ${profile.cognitive_profile.moral_reasoning_stage}` : '',
    profile?.cognitive_profile?.problem_solving_style ? `Problem solving: ${profile.cognitive_profile.problem_solving_style}` : '',
  ].filter(Boolean));
  const anxietyMarkers = Array.isArray(profile?.emotional_profile?.anxiety_markers) ? profile.emotional_profile.anxiety_markers : [];
  renderSection(dom.emotionalSection, [
    profile?.emotional_profile?.empathy_level ? `Empathy level: ${profile.emotional_profile.empathy_level}` : '',
    profile?.emotional_profile?.stress_response ? `Stress response: ${profile.emotional_profile.stress_response}` : '',
    anxietyMarkers.length ? `Anxiety markers: ${anxietyMarkers.join(', ')}` : '',
    profile?.emotional_profile?.emotional_vocabulary ? `Emotional vocabulary: ${profile.emotional_profile.emotional_vocabulary}` : '',
  ].filter(Boolean));
  renderSection(dom.behavioralSection, [
    profile?.behavioral_insights?.leadership_potential ? `Leadership potential: ${profile.behavioral_insights.leadership_potential}` : '',
    profile?.behavioral_insights?.peer_influence ? `Peer influence: ${profile.behavioral_insights.peer_influence}` : '',
    profile?.behavioral_insights?.academic_pressure ? `Academic pressure: ${profile.behavioral_insights.academic_pressure}` : '',
    profile?.behavioral_insights?.resilience ? `Resilience: ${profile.behavioral_insights.resilience}` : '',
  ].filter(Boolean));
  const keyMoments = Array.isArray(profile?.conversation_analysis?.key_moments) ? profile.conversation_analysis.key_moments : [];
  renderSection(dom.conversationSection, [
    profile?.conversation_analysis?.evolution_across_rounds ? `Evolution across rounds: ${profile.conversation_analysis.evolution_across_rounds}` : '',
    profile?.conversation_analysis?.consistency ? `Consistency: ${profile.conversation_analysis.consistency}` : '',
    keyMoments.length ? `Key moments: ${keyMoments.join(' | ')}` : '',
  ].filter(Boolean));

  const keyMomentsEl = document.getElementById('key-moments-section');
  const moments = Array.isArray(profile?.key_moments) ? profile.key_moments : [];
  if (moments.length) {
    keyMomentsEl.innerHTML = '';
    moments.forEach(m => {
      const d = document.createElement('div');
      d.style.cssText = 'margin-bottom:12px;padding:10px;border-left:3px solid var(--warning);background:rgba(212,165,67,0.08);border-radius:4px;';
      d.innerHTML = '<div style="font-style:italic;margin-bottom:4px;color:var(--text);">"' + (m.quote || '').replace(/</g, '&lt;') + '"</div><div style="color:var(--text-muted);font-size:0.85rem;">' + (m.insight || '').replace(/</g, '&lt;') + '</div>';
      keyMomentsEl.appendChild(d);
    });
  } else { keyMomentsEl.textContent = 'No key moments identified.'; }

  const redFlagsEl = document.getElementById('red-flags-section');
  const flags = Array.isArray(profile?.red_flags) ? profile.red_flags : [];
  if (flags.length) {
    redFlagsEl.innerHTML = '';
    flags.forEach(f => {
      const d = document.createElement('div');
      d.style.cssText = 'margin-bottom:6px;padding:8px 12px;background:rgba(224,82,82,0.06);border-radius:6px;color:var(--danger);font-size:0.9rem;';
      d.textContent = '\u26a0 ' + f;
      redFlagsEl.appendChild(d);
    });
  } else { redFlagsEl.textContent = 'No red flags identified.'; }

  document.getElementById('summary-text').textContent = profile?.summary || 'No summary available.';
}

function showAnalysisUnavailable(message) {
  renderSection(dom.personalitySection, []);
  renderSection(dom.cognitiveSection, []);
  renderSection(dom.emotionalSection, []);
  renderSection(dom.behavioralSection, []);
  renderSection(dom.conversationSection, []);
  dom.recommendationsEl.textContent = message || 'Analysis unavailable.';
}

// --- Processing status bar ---
const ANALYSIS_STEPS = [
  'Saving session...',
  'Uploading video...',
  'Analyzing facial expressions...',
  'Analyzing voice patterns...',
  'Generating student profile...',
  'Done!',
];

function ensureStatusBar() {
  let bar = document.getElementById('analysis-status-bar');
  if (bar) return bar;
  bar = document.createElement('div');
  bar.id = 'analysis-status-bar';
  bar.style.cssText = 'position:fixed;top:0;left:0;right:0;z-index:9999;background:#1a1a2e;color:#fff;padding:10px 20px;font-size:14px;font-family:DM Sans,system-ui,sans-serif;display:flex;align-items:center;gap:12px;box-shadow:0 2px 8px rgba(0,0,0,0.3);';
  bar.innerHTML = '<div id="analysis-spinner" style="width:16px;height:16px;border:2px solid rgba(255,255,255,0.3);border-top-color:#4ade80;border-radius:50%;animation:spin 0.8s linear infinite;"></div><div id="analysis-status-text" style="flex:1;">Processing...</div><div id="analysis-progress" style="font-size:12px;color:#9ca3af;">0%</div>';
  const style = document.createElement('style');
  style.textContent = '@keyframes spin{to{transform:rotate(360deg)}}';
  document.head.appendChild(style);
  document.body.prepend(bar);
  return bar;
}

function setAnalysisProgress(step, detail) {
  const bar = ensureStatusBar();
  const textEl = bar.querySelector('#analysis-status-text');
  const pctEl = bar.querySelector('#analysis-progress');
  const spinner = bar.querySelector('#analysis-spinner');
  const label = ANALYSIS_STEPS[step] || detail || 'Processing...';
  const pct = Math.min(100, Math.round((step / (ANALYSIS_STEPS.length - 1)) * 100));
  if (textEl) textEl.textContent = detail ? `${label} — ${detail}` : label;
  if (pctEl) pctEl.textContent = `${pct}%`;
  if (step >= ANALYSIS_STEPS.length - 1 && spinner) {
    spinner.style.borderTopColor = '#4ade80';
    spinner.style.animation = 'none';
    spinner.textContent = '\u2713';
    spinner.style.cssText += 'display:flex;align-items:center;justify-content:center;font-size:14px;';
    setTimeout(() => { bar.style.transition = 'opacity 1s'; bar.style.opacity = '0'; setTimeout(() => bar.remove(), 1000); }, 2000);
  }
}

function setAnalysisError(msg) {
  const bar = ensureStatusBar();
  const textEl = bar.querySelector('#analysis-status-text');
  const spinner = bar.querySelector('#analysis-spinner');
  if (textEl) textEl.textContent = msg;
  if (spinner) {
    spinner.style.animation = 'none';
    spinner.style.borderColor = '#ef4444';
    spinner.textContent = '!';
    spinner.style.cssText += 'display:flex;align-items:center;justify-content:center;font-size:14px;color:#ef4444;';
  }
  bar.style.background = '#2d1b1b';
}

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

// --- End session ---

export async function endSession() {
  // Stop all audio/video immediately
  state.intentionalSessionEnd = true;
  setStatus('Processing...');
  clearInterval(state.timerHandle);
  stopWaveform();

  // Kill playback immediately so AI voice stops
  if (state.geminiPlaybackCtx) {
    try { state.geminiPlaybackCtx.suspend(); } catch {}
  }

  // Stop camera/mic — turns off green light
  if (dom.preview) { dom.preview.srcObject = null; dom.preview.pause(); }
  if (state.mediaStream) {
    state.mediaStream.getTracks().forEach(t => t.stop());
    state.mediaStream = null;
  }

  setAnalysisProgress(0, state.savedSessionId ? `ID: ${state.savedSessionId.slice(0,8)}` : 'Waiting for server...');
  const videoBlob = await finalizeRecording();

  // Stop ingest
  if (state.geminiVideoInterval) { clearInterval(state.geminiVideoInterval); state.geminiVideoInterval = null; }
  if (state.geminiTranscriptTimer) { clearTimeout(state.geminiTranscriptTimer); state.geminiTranscriptTimer = null; }
  if (state.geminiMicProcessor) { try { state.geminiMicProcessor.disconnect(); } catch {} state.geminiMicProcessor = null; }

  // Signal end-of-session to server and wait for save confirmation
  if (state.geminiWs && state.geminiWs.readyState === WebSocket.OPEN) {
    try { state.geminiWs.send(JSON.stringify({ type: 'end_session' })); } catch {}
    await waitForSessionSaved(5000);
  }

  // Close all audio contexts and WebSocket
  if (state.geminiAudioCtx) { try { state.geminiAudioCtx.close(); } catch {} state.geminiAudioCtx = null; }
  if (state.geminiPlaybackCtx) { try { state.geminiPlaybackCtx.close(); } catch {} state.geminiPlaybackCtx = null; }
  if (state.geminiWs) { try { state.geminiWs.close(); } catch {} state.geminiWs = null; }

  const duration = formatTime(Date.now() - state.timerStart);
  const summaryMetaBase = `${state.sessionMeta.name} \u2022 Class ${state.sessionMeta.className} \u2022 ${duration}`;
  document.getElementById('summary-meta').textContent = summaryMetaBase;

  const summaryTranscriptEl = document.getElementById('summary-transcript');
  const formatTranscriptForDisplay = entries => entries.map(e => `${e.role === 'counsellor' ? 'Counsellor' : 'Student'}: ${e.text}`).join('\n');
  const safeTranscriptEntries = state.transcriptEntries.filter(e => e && e.text && e.text.trim());
  summaryTranscriptEl.textContent = safeTranscriptEntries.length ? formatTranscriptForDisplay(safeTranscriptEntries) : dom.transcriptEl.textContent.trim();

  // Download transcript button (Phase 8b)
  const existingDl = document.getElementById('download-transcript-btn');
  if (!existingDl) {
    const dlBtn = document.createElement('button');
    dlBtn.id = 'download-transcript-btn';
    dlBtn.className = 'btn btn-ghost';
    dlBtn.style.cssText = 'width:auto;min-width:180px;margin-top:12px;';
    dlBtn.textContent = 'Download transcript';
    dlBtn.addEventListener('click', () => {
      const text = safeTranscriptEntries.map(e => `${e.role === 'counsellor' ? 'Counsellor' : 'Student'}: ${e.text}`).join('\n\n');
      const blob = new Blob([text], { type: 'text/plain' });
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = `counselai-transcript-${state.sessionMeta.name.replace(/\s+/g, '_')}.txt`;
      a.click();
      URL.revokeObjectURL(a.href);
    });
    const summaryGrid = document.querySelector('.summary-grid');
    if (summaryGrid) summaryGrid.parentElement.insertBefore(dlBtn, summaryGrid.nextSibling);
  }

  showScreen('summary');
  [dom.personalitySection, dom.cognitiveSection, dom.emotionalSection, dom.behavioralSection, dom.conversationSection].forEach(el => el.textContent = 'Analyzing...');
  dom.recommendationsEl.textContent = 'Generating recommendations...';
  dom.profileMetrics.textContent = 'Computing scores...';

  if (!state.savedSessionId) {
    uiLog('ERR', 'No session_id received from server — cannot submit analysis.');
    setAnalysisError('Session was not saved by the server. Analysis cannot proceed.');
    showToast('Session save failed. Please try again or contact support.');
    showAnalysisUnavailable('No session_id available — the server did not confirm the session was saved.');
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
      ? `Video: ${(videoBlob.size / 1024).toFixed(0)}KB`
      : transcriptOnlyFallback
        ? 'Transcript-only analysis'
        : 'No usable recording captured';
    setAnalysisProgress(1, detailText);

    if (!hasVideoPayload) {
      const diagMsg = describeRecordingIssue(mediaStatus);
      console.info(`[CounselAI] Media fallback: ${diagMsg}`, mediaStatus);
      mediaStatus.analysisMode = hasTranscriptData ? 'transcript_only' : 'capture_failed';
      if (!hasTranscriptData) {
        setAnalysisError(diagMsg);
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

    setAnalysisProgress(2, `${finalTranscript.length} turns`);
    const resp = await fetch('/api/analyze-session', { method: 'POST', body: fd });
    if (resp.ok) {
      setAnalysisProgress(4, 'Parsing results...');
      const data = await resp.json();
      const profile = data.profile || {};
      buildMetrics(profile);
      renderFaceAnalysis(data.face_data || {});
      renderVoiceAnalysis(data.voice_data || {});
      renderProfileSections(profile);
      renderRecommendations(profile);
      setAnalysisProgress(5);
    } else {
      const errText = (await resp.text().catch(() => 'Unknown error')).trim();
      const errMsg = errText || `HTTP ${resp.status}`;
      setAnalysisError(`Analysis failed: ${errMsg}`);
      console.error('[CounselAI] Analysis HTTP error:', resp.status, errText);
      showAnalysisUnavailable(`Analysis unavailable: ${errMsg}`);
      showToast(`Analysis failed: ${errMsg}`);
    }
  } catch (err) {
    console.error('[CounselAI] Analysis error:', err);
    setAnalysisError(`Error: ${err.message}`);
    showAnalysisUnavailable(`Analysis unavailable: ${err.message}`);
  }
}
