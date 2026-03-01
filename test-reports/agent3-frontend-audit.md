# Agent 3: Frontend JS Audit — `live.html`

**Date:** 2026-03-01  
**File:** `/home/clawdbot/counsel-ai/templates/live.html`

---

## CRITICAL

### 1. Audio element not appended to DOM — remote AI audio may not play
**Location:** `pc.ontrack` handler in `startSession()`  
The `audioEl` is created via `document.createElement("audio")` but never appended to `document.body`. Many browsers (especially mobile Safari, Chrome on Android) **refuse to play audio** from unattached elements. Worse, `audioEl` is a local variable — it can be garbage-collected after `startSession()` returns, killing playback entirely.

**Fix:** Store as module-level variable and append to DOM.

### 2. `getUserMedia({video: true})` blocks session on devices without a camera
**Location:** `startSession()` media request  
Only the audio track is sent to OpenAI (correct for Realtime API), but video is requested as mandatory. On desktops without webcams or when camera permission is denied, the **entire session fails** — even though video isn't needed for the AI connection.

**Fix:** Request video separately with a try/catch fallback, or make it optional: `{ audio: true, video: { optional: true } }`.

### 3. No ICE server configuration — NAT traversal will fail for many users
**Location:** `pc = new RTCPeerConnection()`  
No `iceServers` config (STUN/TURN). Without at least a public STUN server, connections behind symmetric NATs or restrictive firewalls will fail silently.

**Fix:** Add `{ iceServers: [{ urls: "stun:stun.l.google.com:19302" }] }` at minimum.

---

## HIGH

### 4. `orb.speaking` animation set on track arrival, not actual speech
**Location:** `pc.ontrack` callback  
`orbEl.classList.add("speaking")` fires once when the remote track arrives — not when the AI is actually speaking. The orb stays animated permanently. `response.done` removes it, but during gaps between transcript deltas and responses, the animation state is wrong.

**Fix:** Use Web Audio API `AnalyserNode` on the remote stream for accurate speech detection, or rely solely on data channel transcript events.

### 5. XSS via transcript text — innerHTML used with unsanitized content
**Location:** `addTranscript()` function  
Transcript text from the AI and user speech is inserted via `.innerHTML`. If the AI or transcription returns HTML/script content, it renders as HTML.

**Fix:** Use `.textContent` for the text portion, or create text nodes.

### 6. No cleanup on error during `startSession()`
**Location:** catch block in `startSession()`  
If an error occurs after `getUserMedia` succeeds (e.g., server returns 500), media stream tracks are **never stopped**. Camera/mic indicator stays on, `mediaRecorder` may be left running.

**Fix:** Add cleanup in catch: stop media tracks, stop recorder, close PC.

### 7. `response.create` sent immediately on data channel open — may race with session init
**Location:** `dc.onopen` handler  
The session scenario/instructions are passed via the server's `/api/rtc-connect` endpoint as a query param. But `response.create` is sent with its own instructions immediately on channel open, potentially before the server-side session config has been applied.

**Fix:** Wait for `session.created` or `session.updated` event from the server before sending `response.create`.

---

## MEDIUM

### 8. Timer not cleared between sessions
**Location:** `startSession()` / `endSession()`  
If `startSession` is called without prior `endSession` (e.g., "New Session" skips cleanup), `timerInterval` leaks. Multiple intervals stack up.

**Fix:** `clearInterval(timerInterval)` at start of `startSession()`.

### 9. Recording is full video+audio — large upload on mobile
**Location:** `startRecording()`, `endSession()`  
A 10-min session could be 50-100MB+ of WebM. No upload progress indicator. Mobile data uploads will be very slow or fail.

**Fix:** Audio-only recording option, upload progress bar, or chunked upload.

### 10. No `dc.onclose` / `dc.onerror` / `pc.oniceconnectionstatechange` handlers
If the connection drops mid-session, the UI freezes in "Listening..." with no feedback. User has no idea the session died.

**Fix:** Monitor connection state, show error toast, offer reconnect/end.

### 11. Case study dropdown has no placeholder option
First case study is auto-selected. User can accidentally start with wrong one.

### 12. `endSession()` doesn't check if connection is already closed
Calling `dc.close()` or `pc.close()` on already-closed objects may throw. No guard.

---

## LOW

### 13. `overflow: hidden` on body prevents scrolling on small screens
If form card exceeds viewport (small phones, landscape), users can't scroll to "Start" button.

**Fix:** Use `overflow-x: hidden` or `overflow: auto` on `.welcome`.

### 14. No loading/disabled state on "Start Live Session" button
User can double-click and trigger duplicate `getUserMedia` + WebRTC setup.

**Fix:** Disable button on click, re-enable on error.

### 15. `renderProfile()` uses string concatenation into innerHTML
Similar XSS pattern as #5 but with server-sourced data. Lower risk but still bad practice.

### 16. Transcript `max-height: 32vh` cramped on phones
~205px on a 640px phone. With orb + controls, minimal transcript space. Worse in landscape.

### 17. `transcriptEntries` array grows unbounded
For very long sessions, the array and DOM nodes accumulate. Not practical for typical sessions but worth noting.

### 18. No CSP meta tag or security headers
Minor security hygiene for an internal tool.

---

## Summary

| Severity | Count |
|----------|-------|
| CRITICAL | 3     |
| HIGH     | 4     |
| MEDIUM   | 5     |
| LOW      | 6     |

**Top 5 priorities:**
1. **Fix audio element DOM attachment** (CRITICAL #1) — AI voice won't play on most mobile browsers
2. **Make video optional** (CRITICAL #2) — blocks users without cameras entirely
3. **Add ICE servers** (CRITICAL #3) — connections fail behind NATs
4. **Sanitize transcript HTML** (HIGH #5) — XSS risk
5. **Add connection state monitoring** (MEDIUM #10) — silent failures leave users stranded
