"""CounselAI FastAPI application entry point.

Start with:
    uvicorn counselai.api.app:app --host 0.0.0.0 --port 8501
"""

import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

# ---------------------------------------------------------------------------
# Resolve project root (3 levels up: src/counselai/api/app.py)
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from dotenv import load_dotenv  # noqa: E402

from google import genai  # noqa: E402
from google.genai import types as gt  # noqa: E402
from counselai.prompts import build_counsellor_prompt  # noqa: E402

import db as legacy_db  # noqa: E402

logger = logging.getLogger(__name__)
templates = Jinja2Templates(directory=str(_PROJECT_ROOT / "templates"))


# ---------------------------------------------------------------------------
# Lifespan: startup / shutdown
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(application: FastAPI):
    """Pre-init Gemini client and legacy DB on startup."""
    from counselai.api.gemini_client import init_gemini_client

    legacy_db.init_db()
    try:
        init_gemini_client()
    except Exception as exc:
        logger.warning("Gemini client pre-init failed (will retry lazily): %s", exc)
    yield


# ---------------------------------------------------------------------------
# App creation
# ---------------------------------------------------------------------------
app = FastAPI(title="CounselAI", version="0.2.0", lifespan=lifespan)

# ---------------------------------------------------------------------------
# Mount routers
# ---------------------------------------------------------------------------
from counselai.api.routes.gemini_ws import router as gemini_ws_router  # noqa: E402
from counselai.api.routes.legacy import router as legacy_router  # noqa: E402
from counselai.api.routes.dashboard import router as dashboard_router  # noqa: E402
from counselai.api.routes.analytics import router as analytics_router  # noqa: E402
from counselai.api.routes.analytics import feedback_router  # noqa: E402

app.include_router(gemini_ws_router, prefix="/api", tags=["gemini"])
app.include_router(legacy_router, prefix="/api", tags=["legacy"])
app.include_router(dashboard_router, prefix="/api/v1/dashboard", tags=["dashboard"])
app.include_router(analytics_router)  # mounted at /api/analytics (prefix in router)
app.include_router(feedback_router)  # mounted at /api/sessions (prefix in router)

# ---------------------------------------------------------------------------
# Provider config (will move to settings.py in Task 2)
# ---------------------------------------------------------------------------
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_WS_URL = (
    "wss://generativelanguage.googleapis.com/ws/"
    "google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent"
)
GEMINI_MODEL = "models/gemini-2.5-flash-native-audio-preview-12-2025"

_gemini_client = None


def _get_gemini_client():
    """Lazy-init the Gemini client so import works without API keys set."""
    global _gemini_client
    if _gemini_client is None:
        api_key = os.environ.get("GEMINI_API_KEY", "")
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY not set")
        _gemini_client = genai.Client(
            api_key=api_key,
            http_options={"api_version": "v1beta"},
        )
        print("[init] Gemini client initialized")
    return _gemini_client

# Legacy alias — kept for the OpenAI RTC endpoint which still uses a flat string.
# The Gemini WS endpoint uses build_counsellor_prompt() directly.
COUNSELLOR_INSTRUCTIONS = build_counsellor_prompt()


# ---------------------------------------------------------------------------
# Template-serving routes
# ---------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    response = templates.TemplateResponse("live.html", {"request": request})
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return response


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    response = templates.TemplateResponse("dashboard.html", {"request": request})
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return response


@app.get("/api/case-studies")
async def get_case_studies():
    return JSONResponse({"case_studies": CASE_STUDIES})


@app.post("/api/rtc-connect")
async def rtc_connect(request: Request):
    import httpx

    if not OPENAI_API_KEY:
        return Response(content="OPENAI_API_KEY not set", status_code=500)

    sdp_offer = (await request.body()).decode()
    scenario = request.query_params.get("scenario", "")
    session_json = json.dumps(
        {
            "type": "realtime",
            "model": "gpt-realtime",
            "instructions": COUNSELLOR_INSTRUCTIONS + scenario,
            "audio": {
                "output": {"voice": "sage"},
                "input": {
                    "transcription": {"model": "gpt-4o-transcribe"},
                    "turn_detection": {
                        "type": "server_vad",
                        "threshold": 0.5,
                        "silence_duration_ms": 500,
                    },
                },
            },
        }
    )
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            "https://api.openai.com/v1/realtime/calls",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
            files=[
                ("sdp", (None, sdp_offer, "application/sdp")),
                ("session", (None, session_json, "application/json")),
            ],
        )
    if resp.status_code not in (200, 201):
        request_id = resp.headers.get("x-request-id", "")
        body_preview = resp.text[:1200]
        print(f"[rtc-connect] OpenAI realtime call failed status={resp.status_code} "
              f"request_id={request_id} body={body_preview}")
    media_type = "application/sdp" if resp.status_code in (200, 201) else "text/plain"
    return Response(content=resp.text, status_code=resp.status_code, media_type=media_type)


@app.post("/api/gemini-transcribe")
async def gemini_transcribe(audio: UploadFile = File(...)):
    """Transcribe audio using Gemini."""
    try:
        audio_bytes = await audio.read()
        response = _get_gemini_client().models.generate_content(
            model="models/gemini-3.1-flash-lite-preview",
            contents=[
                "Transcribe the human speech in this audio to text. Return ONLY the exact "
                "spoken words in the original language (Hindi/Hinglish/English). If there is "
                "no clear speech, return an empty string. Do NOT describe sounds or noises.",
                gt.Part.from_bytes(data=audio_bytes, mime_type="audio/wav"),
            ],
            config=gt.GenerateContentConfig(),
        )
        text = (response.text or "").strip()
        skip_phrases = [
            "silence", "no speech", "no clear speech",
            "no audio", "no words", "empty",
        ]
        if any(s in text.lower() for s in skip_phrases) and len(text) < 50:
            text = ""
        return JSONResponse({"transcript": text})
    except Exception as e:
        print(f"[transcribe] Error: {e}")
        return JSONResponse({"error": str(e)}, 500)


@app.websocket("/api/gemini-ws")
async def gemini_ws_proxy(ws: WebSocket):
    """WebSocket proxy: browser <-> Gemini Live API using official SDK."""
    await ws.accept()
    scenario = ws.query_params.get("scenario", "")
    student_name = ws.query_params.get("name", "Student")

    config = gt.LiveConnectConfig(
        response_modalities=["AUDIO"],
        speech_config=gt.SpeechConfig(
            voice_config=gt.VoiceConfig(
                prebuilt_voice_config=gt.PrebuiltVoiceConfig(voice_name="Zephyr")
            )
        ),
    )

    session = None
    try:
        async with _get_gemini_client().aio.live.connect(
            model=GEMINI_MODEL, config=config
        ) as session:
            print(f"[gemini-ws] Connected to {GEMINI_MODEL} with audio output enabled")
            await ws.send_json({"type": "setup_complete"})

            session_prompt = build_counsellor_prompt(
                scenario=scenario, student_name=student_name
            )
            await session.send_client_content(
                turns=gt.Content(parts=[gt.Part(text=session_prompt)]),
                turn_complete=False,
            )
            print("[gemini-ws] System instructions sent via client content")

            # Send silent audio to trigger initial greeting
            sample_rate = 24000
            duration_ms = 100
            num_samples = int(sample_rate * duration_ms / 1000)
            silent_audio = struct.pack("<" + "h" * num_samples, *([0] * num_samples))
            await session.send_realtime_input(
                audio=gt.Blob(data=silent_audio, mime_type="audio/pcm")
            )
            await session.send_realtime_input(audio_stream_end=True)
            print("[gemini-ws] Trigger audio sent - waiting for model to greet...")

            async def browser_to_gemini():
                try:
                    while True:
                        data = await ws.receive_text()
                        msg = json.loads(data)
                        ri = msg.get("realtimeInput", {})
                        chunks = ri.get("mediaChunks", [])
                        for chunk in chunks:
                            mime = chunk.get("mimeType", "")
                            b64data = chunk.get("data", "")
                            raw = base64.b64decode(b64data)
                            if mime.startswith("audio/"):
                                await session.send_realtime_input(
                                    audio=gt.Blob(data=raw, mime_type="audio/pcm")
                                )
                            elif mime.startswith("image/"):
                                await session.send_realtime_input(
                                    video=gt.Blob(data=raw, mime_type=mime)
                                )
                except WebSocketDisconnect:
                    print("[gemini-ws] Browser disconnected")
                except Exception as e:
                    print(f"[gemini-ws] browser->gemini error: {e}")

            async def gemini_to_browser():
                msg_count = 0
                counsellor_audio_chunks = []
                try:
                    async for response in session.receive():
                        msg_count += 1
                        out = {"serverContent": {}}
                        sc = out["serverContent"]
                        srv = response.server_content

                        audio_data = None
                        text_data = None
                        if srv and srv.model_turn and srv.model_turn.parts:
                            for part in srv.model_turn.parts:
                                if part.inline_data and part.inline_data.data:
                                    audio_data = part.inline_data.data
                                if part.text:
                                    text_data = part.text

                        if audio_data:
                            sc["modelTurn"] = {
                                "parts": [
                                    {
                                        "inlineData": {
                                            "data": base64.b64encode(audio_data).decode(),
                                            "mimeType": "audio/pcm",
                                        }
                                    }
                                ]
                            }
                            counsellor_audio_chunks.append(audio_data)

                        if text_data:
                            if "modelTurn" not in sc:
                                sc["modelTurn"] = {"parts": []}
                            sc["modelTurn"]["parts"].append({"text": text_data})

                        if srv:
                            if srv.turn_complete:
                                sc["turnComplete"] = True
                                counsellor_audio_chunks = []
                            if srv.input_transcription:
                                t = getattr(srv.input_transcription, "text", "")
                                if t and t.strip():
                                    sc["inputTranscription"] = {"text": t.strip()}
                            if srv.output_transcription:
                                t = getattr(srv.output_transcription, "text", "")
                                if t and t.strip():
                                    sc["outputTranscription"] = {"text": t.strip()}
                            if srv.generation_complete:
                                sc["generationComplete"] = True

                        if response.setup_complete:
                            continue

                        if sc:
                            await ws.send_json(out)

                except Exception as e:
                    print(f"[gemini-ws] gemini->browser error: {e}")
                    traceback.print_exc()

            done, pending = await asyncio.wait(
                [
                    asyncio.create_task(browser_to_gemini()),
                    asyncio.create_task(gemini_to_browser()),
                ],
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()

    except Exception as e:
        print(f"[gemini-ws] Error: {e}")
        traceback.print_exc()
        try:
            await ws.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass
    finally:
        try:
            await ws.close()
        except Exception:
            pass


@app.post("/api/analyze-session")
async def analyze_session(
    video: UploadFile = File(...),
    transcript: str = Form("[]"),
    student_name: str = Form("Student"),
    student_class: str = Form("10"),
    student_section: str = Form(""),
    student_school: str = Form(""),
    student_age: int = Form(15),
    session_start_time: str = Form(None),
    session_end_time: str = Form(None),
):
    try:
        transcript_data = json.loads(transcript)
    except (json.JSONDecodeError, TypeError):
        transcript_data = []

    if os.environ.get("COUNSELAI_DEBUG"):
        try:
            with open("/tmp/counselai_last_transcript.json", "w") as f:
                json.dump(transcript_data, f, indent=2)
        except Exception as exc:
            print(f"[analyze] failed to save transcript: {exc}")

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".webm")
    tmp.write(await video.read())
    tmp.close()

    face_data, voice_data = {}, {}
    try:
        import face_analyzer
        import utils

        frames_dir = tempfile.mkdtemp()
        utils.save_frames_from_video(tmp.name, frames_dir, interval=3)
        face_data = face_analyzer.analyze_frames(frames_dir)
    except Exception as exc:
        print(f"Face analysis skipped: {exc}")
        traceback.print_exc()

    try:
        import utils
        import voice_analyzer

        audio_path = utils.extract_audio_from_video(tmp.name)
        if audio_path:
            voice_data = voice_analyzer.analyze_audio(audio_path)
    except Exception as exc:
        print(f"Voice analysis skipped: {exc}")
        traceback.print_exc()

    session_end = session_end_time or datetime.now(timezone.utc).isoformat()

    has_transcripts = len(transcript_data) > 0 and any(
        e.get("text", "").strip() for e in transcript_data
    )
    has_audio_data = voice_data and voice_data.get("audio_duration", 0) > 5

    session_duration = 0
    try:
        if session_start_time and session_end:
            start = datetime.fromisoformat(session_start_time.replace("Z", "+00:00"))
            end = datetime.fromisoformat(session_end.replace("Z", "+00:00"))
            session_duration = (end - start).total_seconds()
    except Exception:
        pass

    has_duration = session_duration > 30

    if not (has_transcripts or has_audio_data or has_duration):
        return JSONResponse(
            {"error": "Insufficient session data for analysis."},
            400,
        )

    try:
        import profile_generator

        profile = profile_generator.generate_profile(
            {
                "student_info": {"name": student_name, "class": student_class},
                "rounds": [
                    {"transcription": e.get("text", ""), "role": e.get("role", "student")}
                    for e in transcript_data
                ],
                "face_data": face_data,
                "voice_data": voice_data,
            }
        )
        saved_id = db.save_session(
            source="realtime",
            external_session_id=None,
            student_info={
                "name": student_name,
                "class": student_class,
                "section": student_section,
                "school": student_school,
                "age": student_age,
            },
            session_start_time=session_start_time,
            session_end_time=session_end,
            transcript=transcript_data,
            face_analysis=face_data,
            voice_analysis=voice_data,
            profile=profile,
        )
        return JSONResponse(
            {
                "profile": _sanitize(profile),
                "face_data": _sanitize(face_data),
                "voice_data": _sanitize(voice_data),
                "session_id": saved_id,
            }
        )
    except Exception as exc:
        print(f"Profile generation failed: {exc}")
        traceback.print_exc()
        profile = {"summary": f"Analysis error: {exc}"}
        saved_id = db.save_session(
            source="realtime",
            external_session_id=None,
            student_info={
                "name": student_name,
                "class": student_class,
                "section": student_section,
                "school": student_school,
                "age": student_age,
            },
            session_start_time=session_start_time,
            session_end_time=session_end,
            transcript=transcript_data,
            face_analysis=face_data,
            voice_analysis=voice_data,
            profile=profile,
        )
        return JSONResponse({"profile": profile, "session_id": saved_id})
    finally:
        os.unlink(tmp.name)


@app.get("/api/sessions")
async def get_sessions():
    return JSONResponse({"sessions": db.list_sessions()})


@app.get("/api/sessions/{session_id}")
async def get_session_detail(session_id: int):
    session = db.get_session(session_id)
    if not session:
        return JSONResponse({"error": "Session not found"}, 404)
    return JSONResponse(session)
