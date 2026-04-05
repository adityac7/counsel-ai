# CounselAI Live — Architecture

## Live Session API

### WebSocket /ws/gemini
Real-time bidirectional audio via Gemini Live API.
- Client sends PCM audio chunks
- Server relays to Gemini, streams back audio + transcription
- Model: `gemini-live-2.5-flash-preview`

### POST /api/case-studies
Returns available case study scenarios.

### POST /api/analyze-session (multipart)
Fields: `video` (optional webm), `transcript` (JSON), student metadata.

## Live Session UX Flow

### Layout (2-column on desktop, stacked on mobile)
LEFT (60%): Video preview circle + glowing orb + status + timer
RIGHT (40%): Case study question card (always visible for reference)
BOTTOM (full width): Live transcript + End Session button

### AI Counsellor Behavior
1. AI reads the case study scenario aloud to the student
2. AI asks: "What do you think about this? What would you do?"
3. Student responds via voice
4. AI listens, then asks probing WHY questions
5. AI keeps original case study context throughout
6. After 8-10 exchanges, AI summarizes observations
7. Turn detection: server VAD with 500ms silence threshold

### Post-Session Analysis Pipeline
1. Stop MediaRecorder -> get video blob
2. Upload to /api/analyze-session (multipart: video + transcript JSON)
3. Server: extract frames (ffmpeg) -> DeepFace face analysis
4. Server: extract audio (ffmpeg) -> librosa voice analysis
5. Server: transcript + face + voice -> Gemini profile generation
6. Return structured profile (scores, summary, recommendations)
