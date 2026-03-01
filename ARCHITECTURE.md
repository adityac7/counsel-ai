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
