# Agent 5: Analyzer Module Test Report

**Date:** 2026-03-01  
**Status:** ⚠️ Modules work individually, but endpoint has critical integration gap

---

## 1. face_analyzer.py ✅

- **Imports:** All work (cv2, DeepFace with TensorFlow backend — CPU mode, no GPU)
- **Exported functions:** `analyze_single_frame()`, `analyze_frames()`
- **Missing file handling:** ✅ Returns `{}` gracefully
- **No faces detected:** Returns result with `dominant_emotion` still populated (DeepFace with `enforce_detection=False` guesses anyway)
- **Blurry frame handling:** ✅ Skips blurry frames via Laplacian variance check
- **WebM frames:** ✅ Works with frames extracted from .webm

## 2. voice_analyzer.py ⚠️

- **Imports:** librosa ✅, **parselmouth ❌ NOT INSTALLED** (`HAS_PARSELMOUTH = False`)
- **Exported functions:** `analyze_audio()`, `detect_pauses()`
- **Missing file handling:** ✅ Returns `{}` gracefully
- **Parselmouth fallback:** ✅ Code handles it — falls back to zeroed pitch/voice_quality metrics
- **Audio formats:** Anything librosa supports (wav, mp3, ogg, flac, webm audio)
- **Test result:** Returns valid analysis with 7 keys; confidence score = 0.9
- **Issue:** Without parselmouth, pitch analysis and voice quality (tremor, breathiness, steadiness) are all zeroed. **Install `praat-parselmouth` for full analysis.**

## 3. utils.py ✅

- **`extract_audio_from_video()`:** ✅ Works with .webm → .wav via pydub/ffmpeg
- **`save_frames_from_video()`:** ✅ Works with .webm → JPG frames at configurable interval
- **Missing file handling:** `extract_audio` raises `FileNotFoundError` ✅; `save_frames` returns `[]` ✅
- **Additional:** `create_pdf_report()`, `format_duration()`, `get_emotion_color()`

## 4. Real Video Test ✅

3-second test .webm (testsrc + 440Hz sine): extracted 3 frames, audio to .wav, face and voice analysis both returned valid results.

## 5. Integration with `/api/analyze-session` ❌ CRITICAL BUG

**The endpoint does NOT use face_analyzer, voice_analyzer, or utils at all.**

In `realtime_server.py` lines 94-130:
1. Receives video upload, saves as temp .webm ✅
2. Imports `profile_generator` ✅
3. **Never calls:**
   - `utils.save_frames_from_video()` to extract frames
   - `utils.extract_audio_from_video()` to get audio
   - `face_analyzer.analyze_frames()` for facial expressions
   - `voice_analyzer.analyze_audio()` for voice prosody
4. `session_data["face_data"]` and `session_data["voice_data"]` are always `{}`
5. Temp .webm file never cleaned up (leaks in /tmp)

### Missing code that should be added:
```python
frames_dir = tempfile.mkdtemp()
frames = utils.save_frames_from_video(tmp.name, frames_dir)
audio_path = utils.extract_audio_from_video(tmp.name)
transcript_text = " ".join(e.get("text","") for e in transcript_data)
session_data["face_data"] = face_analyzer.analyze_frames(frames_dir)
session_data["voice_data"] = voice_analyzer.analyze_audio(audio_path, transcript_text)
```

---

## Summary

| Component | Import | Functionality | Error Handling | Integration |
|-----------|--------|--------------|----------------|-------------|
| face_analyzer.py | ✅ | ✅ | ✅ | ❌ Not called |
| voice_analyzer.py | ⚠️ no parselmouth | ✅ (degraded) | ✅ | ❌ Not called |
| utils.py | ✅ | ✅ | ✅ | ❌ Not called |

**Bottom line:** All three modules work correctly in isolation. The critical problem is `/api/analyze-session` never invokes them — face/voice data is always empty. Needs wiring up + `pip install praat-parselmouth`.
