# CounselAI Fix Plan — 5 Agent Teams

## Problem Summary
Three critical failures in the post-session analysis pipeline:
1. **Transcript**: Frontend JS uses wrong event names → 0 entries sent to backend
2. **Voice**: webm opus audio cant be parsed by librosa → needs ffmpeg conversion to wav
3. **Face**: Frames marked blurry due to low BLUR_THRESHOLD + frame extraction fragile
4. **Frontend UX**: No real-time transcript visible, no transcript on summary page
5. **Summary rendering**: Frontend renderProfileSections never shows data even when profile JSON valid

## Agent 1: Frontend Transcript & Events (templates/live.html)
Fix ALL data channel event handling + real-time transcript display:
- Event names MUST be: response.output_audio_transcript.delta and response.output_audio_transcript.done (NOT response.audio_transcript.*)
- Add conversation.item.done handler for student text extraction: when item.role=user, iterate item.content[] and find entries with type=input_audio that have a transcript field
- Ensure transcriptEntries[] in-memory array populated correctly by addEntry()
- Ensure addEntry() creates visible DOM elements in transcript panel  
- Add cache-busting: <meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
- Verify endSession() sends correct transcript JSON to /api/analyze-session
- Remove the debug-log div at bottom (cleanup)
- Test: after changes, transcriptEntries.length > 0 after any AI response

## Agent 2: Frontend Summary & Report Rendering (templates/live.html)
Fix summary page to correctly render ALL profile data:
- Audit renderProfileSections() — ensure it maps ALL profile JSON keys to DOM sections
- The profile JSON has these keys: summary, personality_snapshot, cognitive_profile, emotional_profile, behavioral_insights, conversation_analysis, key_moments, reasoning, red_flags, recommendations
- Add score metrics rendering (critical_thinking, eq_score, confidence, perspective_taking as visual numbers/bars)
- Add key_moments rendering with quote + insight cards
- Add red_flags section with warning styling
- Add recommendations as numbered list
- Add full conversation transcript section at bottom of summary page
- Ensure loading states (Analyzing...) properly replaced by real data
- Handle edge cases: empty arrays, missing keys, null values gracefully
- Show No data only if the key is truly missing/empty, not if rendering code has a bug

## Agent 3: Voice Analysis Pipeline (voice_analyzer.py + utils.py)
Fix audio extraction and analysis:
- In utils.py extract_audio_from_video(): Replace pydub with ffmpeg subprocess:
  import subprocess; subprocess.run(["ffmpeg", "-y", "-i", video_path, "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1", output_wav], check=True, capture_output=True)
- Handle ffmpeg not found gracefully (try/except, log warning)
- Remove pydub import from utils.py (keep other pydub-free functions)
- Ensure librosa.load() works on the resulting wav
- Parselmouth is NOT available on this system — replace ALL parselmouth usage with librosa alternatives:
  - Pitch: use librosa.pyin(y, fmin=75, fmax=500) instead of parselmouth pitch
  - Voice quality (jitter/shimmer/HNR): compute approximations from librosa or just return defaults
  - Remove parselmouth import entirely, remove HAS_PARSELMOUTH flag
- Test: voice_analyzer.analyze_audio() should return valid dict with speech_rate, pauses, pitch, volume keys

## Agent 4: Face Analysis Pipeline (face_analyzer.py + utils.py)
Fix frame extraction and face detection:
- In utils.py save_frames_from_video(): Replace OpenCV VideoCapture with ffmpeg:
  subprocess.run(["ffmpeg", "-y", "-i", video_path, "-vf", f"fps=1/{interval}", "-q:v", "2", f"{output_dir}/frame_%04d.jpg"], check=True, capture_output=True)
- In face_analyzer.py: Lower BLUR_THRESHOLD from 100.0 to 25.0 (webcam frames are naturally softer)
- Add fallback: if ALL frames are blurry, pick the top 3 least-blurry frames and analyze those anyway
- Return partial data even when some frames fail — never return empty dict if frames exist
- Handle no face detected gracefully — return summary with neutral defaults instead of empty dict
- Keep DeepFace with enforce_detection=False and detector_backend=opencv
- Remove the cv2.VideoCapture import if no longer needed after ffmpeg switch

## Agent 5: Server Integration & Robustness (realtime_server.py + profile_generator.py)
Make the analysis pipeline robust end-to-end:
- In realtime_server.py: Add Cache-Control no-store header on HTML response (index route)
- Add ffmpeg availability check at startup (just log warning if missing)
- In /api/analyze-session: Add full traceback logging for face/voice exceptions
- Save raw transcript to /tmp/counselai_last_transcript.json for debugging
- Never return empty profile — if face+voice fail, still generate transcript-only profile
- Ensure face_data and voice_data failures dont block profile generation (already partially done)
- In profile_generator.py: Increase max_completion_tokens from 1200 to 2500
- Add 60-second timeout to OpenAI API call
- Run: sudo systemctl restart counselai after ALL changes

## IMPORTANT CONSTRAINTS
- Do NOT create new files — only modify existing ones
- Max 400 lines per file
- Use httpx (not aiohttp) for any HTTP calls
- Python 3.12, venv at /home/clawdbot/counsel-ai/venv
- ffmpeg is already installed on the system
- OpenAI API key is in environment variable OPENAI_API_KEY
- After all changes: run sudo systemctl restart counselai
