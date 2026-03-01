# CounselAI Live — Architecture

## Verified API Contract

### POST /v1/realtime/calls (multipart)
Fields: `sdp` (application/sdp) + `session` (application/json)

Session config (ONLY these fields accepted):
```json
{
  "type": "realtime",
  "model": "gpt-4o-realtime-preview",
  "instructions": "Your counsellor instructions here",
  "audio": {"output": {"voice": "sage"}}
}
```

Returns: **201** with SDP answer (application/sdp)

### Data Channel "oai-events" (after WebRTC connects)
Send session.update for:
```json
{
  "type": "session.update",
  "session": {
    "turn_detection": {"type": "server_vad", "threshold": 0.5, "silence_duration_ms": 500},
    "input_audio_transcription": {"model": "whisper-1"}
  }
}
```

### Events from OpenAI (via data channel)
- `session.created` / `session.updated`
- `response.audio_transcript.delta` (streaming AI text)
- `response.audio_transcript.done` (final AI text)  
- `response.done` (AI finished speaking)
- `conversation.item.input_audio_transcription.completed` (student text)
- `input_audio_buffer.speech_started` / `speech_stopped`
- `error`

Audio comes via WebRTC media track (not data channel).

## WebRTC Client Requirements
1. `new RTCPeerConnection({iceServers:[{urls:"stun:stun.l.google.com:19302"}]})`
2. `pc.addTransceiver("audio", {direction:"sendrecv"})` then replaceTrack with mic
3. `pc.createOffer()` then `pc.setLocalDescription(offer)`
4. WAIT for `pc.iceGatheringState === "complete"` before sending SDP
5. POST `pc.localDescription.sdp` to server
6. `pc.setRemoteDescription({type:"answer", sdp: responseSdp})`
7. Audio element MUST be in DOM (not a variable), call `.play()` on ontrack
8. Accept both 200 and 201 as success from server

## Live Session UX Flow

### Layout (2-column on desktop, stacked on mobile)
LEFT (60%): Video preview circle + glowing orb + status + timer
RIGHT (40%): Case study question card (always visible for reference)
BOTTOM (full width): Live transcript + End Session button

### AI Counsellor Behavior
1. AI reads the case study scenario aloud to the student
2. AI asks: "What do you think about this? What would you do?"
3. Student responds via voice
4. AI listens, then asks probing WHY questions:
   - "Why do you feel that way?"
   - "What if [scenario twist]?"
   - "You mentioned [X], can you tell me more?"
5. AI keeps original case study context throughout
6. After 3-4 exchanges, AI summarizes observations
7. Turn detection: server_vad with 500ms silence threshold

### Post-Session Analysis Pipeline
1. Stop MediaRecorder → get video blob
2. Upload to /api/analyze-session (multipart: video + transcript JSON)
3. Server: extract frames (ffmpeg) → DeepFace face analysis
4. Server: extract audio (ffmpeg) → librosa voice analysis  
5. Server: transcript + face + voice → GPT-5.2 profile generation
6. Server: MiniMax cross-validation
7. Return structured profile (scores, summary, recommendations)
