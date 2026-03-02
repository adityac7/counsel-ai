"""CounselAI Live — WebRTC Realtime server."""
import json
import os
import tempfile
import traceback
from datetime import datetime, timezone
from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.templating import Jinja2Templates
from case_studies import CASE_STUDIES
import db

app = FastAPI()
templates = Jinja2Templates(directory="templates")
db.init_db()
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
COUNSELLOR_INSTRUCTIONS = (
    "You are a kind, trusted Indian school counsellor for classes 9-12. Sound like a "
    "real caring teacher, not a diagnostic tool.\n"
    "Your tone must be warm, patient, and empathetic in natural Hinglish. Use gentle "
    "phrases naturally when suitable: beta, accha, hmm, dekho, theek hai, aur sunao.\n"
    "Do not run the session like rapid-fire questioning. First acknowledge what the "
    "student shared, reflect it briefly in simple words, then ask only ONE thoughtful "
    "next question.\n"
    "Most responses should be 3-5 sentences: build safety, show understanding, add a "
    "small observation, and then continue with one clear question.\n"
    "You are allowed to validate and normalize the student's experience. Do not only ask "
    "questions; you can share brief supportive observations that help rapport.\n"
    "Keep pacing calm and conversational. Avoid interrogation style, avoid fragmented "
    "one-liners, and avoid jumping too quickly to the next probe.\n"
    "If the student shares something difficult, respond with care first (example style: "
    "\"Accha beta, ye kaafi mushkil lag raha hai...\") before exploring further.\n"
    "Avoid clinical labels, diagnosis, or formal psychological jargon. Prefer curious, "
    "human language such as: \"Dekho beta...\", \"Mujhe batao...\", \"Ye toh...\", "
    "\"Aur sunao...\".\n"
    "For the first response of each session: greet warmly, set a safe tone, and read the "
    "case study naturally in conversational Hinglish instead of robotic phrasing.\n\n"
)
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
            "audio": {"output": {"voice": "sage"}},
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
        print(
            f"[rtc-connect] OpenAI realtime call failed status={resp.status_code} "
            f"body={resp.text[:1200]}"
        )
    media_type = "application/sdp" if resp.status_code in (200, 201) else "text/plain"
    return Response(content=resp.text, status_code=resp.status_code, media_type=media_type)
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
    try:
        with open("/tmp/counselai_last_transcript.json", "w") as f:
            json.dump(transcript_data, f, indent=2)
        print("[analyze] saved transcript to /tmp/counselai_last_transcript.json")
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
    print(f"[analyze] transcript entries received: {len(transcript_data)}")
    if transcript_data:
        print(f"[analyze] first transcript entry: {transcript_data[0]}")
    session_data = {
        "student_info": {"name": student_name, "class": student_class},
        "rounds": [
            {"transcription": e.get("text", ""), "role": e.get("role", "student")}
            for e in transcript_data
        ],
        "face_data": face_data,
        "voice_data": voice_data,
    }
    session_end = session_end_time or datetime.now(timezone.utc).isoformat()
    try:
        import profile_generator
        profile = profile_generator.generate_profile(session_data)
        print(f"[analyze] profile keys: {list(profile.keys())}")
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
            {"profile": profile, "face_data": face_data, "voice_data": voice_data, "session_id": saved_id}
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
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8501)
