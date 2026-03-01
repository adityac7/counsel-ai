"""CounselAI Live — WebRTC Realtime server."""
import os, json, tempfile

from fastapi import FastAPI, Request, UploadFile, File, Form
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.templating import Jinja2Templates

from case_studies import CASE_STUDIES

app = FastAPI()
templates = Jinja2Templates(directory="templates")

OPENAI_KEY = os.environ.get("OPENAI_API_KEY", "")

COUNSELLOR_INSTRUCTIONS = (
    "You are an experienced, warm Indian school counsellor conducting a live "
    "counselling session with a student (class 9-12). Your job is to:\n"
    "1. Read the case study to the student warmly\n"
    "2. Ask what they think about the situation\n"
    "3. Listen carefully, ask probing why questions\n"
    "4. Note emotional cues — if they sound hesitant, probe that area\n"
    "5. Challenge surface-level answers gently\n"
    "6. Reference specific things they said earlier\n"
    "7. Be culturally aware of Indian school dynamics\n"
    "8. After 3-4 exchanges, summarize what you learned\n"
    "9. Never diagnose or label. Only observe, probe, and reflect.\n\n"
    "Keep responses concise (2-3 sentences). Use Hindi words occasionally "
    "(beta, accha, hmm). Be warm but professionally probing."
)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("live.html", {"request": request})


@app.post("/api/rtc-connect", response_class=Response)
async def rtc_connect(request: Request):
    """Proxy browser SDP offer to OpenAI /v1/realtime/calls via multipart."""
    import httpx

    if not OPENAI_KEY:
        return Response(content="OPENAI_API_KEY not set", status_code=500)

    sdp_offer = (await request.body()).decode()
    scenario = request.query_params.get("scenario", "")

    instructions = COUNSELLOR_INSTRUCTIONS
    if scenario:
        instructions += f"\n\nCase Study:\n{scenario}"

    session_config = json.dumps({
        "type": "realtime",
        "model": "gpt-4o-realtime-preview",
        "voice": "sage",
        "instructions": instructions,
        "turn_detection": {"type": "server_vad", "threshold": 0.5, "silence_duration_ms": 500},
        "input_audio_transcription": {"model": "whisper-1"},
    })

    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(
            "https://api.openai.com/v1/realtime/calls",
            headers={"Authorization": f"Bearer {OPENAI_KEY}"},
            files=[
                ("sdp", (None, sdp_offer, "application/sdp")),
                ("session", (None, session_config, "application/json")),
            ],
        )
        return Response(content=r.text, status_code=r.status_code,
                        media_type="application/sdp" if r.status_code == 200 else "text/plain")


@app.get("/api/case-studies")
async def get_case_studies():
    return JSONResponse({"case_studies": CASE_STUDIES})


@app.post("/api/analyze-session")
async def analyze_session(
    video: UploadFile = File(...),
    transcript: str = Form("[]"),
    student_name: str = Form("Student"),
    student_class: str = Form("10"),
):
    """Post-session: process video → face/voice analysis → profile."""
    try:
        transcript_data = json.loads(transcript)
    except (json.JSONDecodeError, TypeError):
        transcript_data = []

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".webm")
    tmp.write(await video.read())
    tmp.close()

    face_data, voice_data = {}, {}
    try:
        import utils, face_analyzer
        frames_dir = tempfile.mkdtemp()
        utils.save_frames_from_video(tmp.name, frames_dir, interval=3)
        face_data = face_analyzer.analyze_frames(frames_dir)
    except Exception as e:
        print(f"Face analysis skipped: {e}")

    try:
        import utils, voice_analyzer
        audio_path = utils.extract_audio_from_video(tmp.name)
        if audio_path:
            voice_data = voice_analyzer.analyze_audio(audio_path)
    except Exception as e:
        print(f"Voice analysis skipped: {e}")

    session_data = {
        "student_info": {"name": student_name, "class": student_class},
        "rounds": [{"transcription": e.get("text", ""), "role": e.get("role", "student")} for e in transcript_data],
        "face_data": face_data,
        "voice_data": voice_data,
    }

    try:
        import profile_generator
        profile = profile_generator.generate_profile(session_data)
        return JSONResponse({"profile": profile})
    except Exception as e:
        return JSONResponse({"profile": {"summary": f"Analysis error: {e}"}})
    finally:
        os.unlink(tmp.name)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8501)
