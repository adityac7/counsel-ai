"""CounselAI Live — WebRTC Realtime server."""
import json
import os
import tempfile
import traceback
from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.templating import Jinja2Templates
from case_studies import CASE_STUDIES
app = FastAPI()
templates = Jinja2Templates(directory="templates")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
COUNSELLOR_INSTRUCTIONS = (
    "You are a warm, neutral Indian school counsellor (class 9-12). During the "
    "session you must ONLY ask questions; never praise, critique, interpret, or lead.\n"
    "Ask ONE clear question at a time. Wait for the student's answer before asking "
    "the next probing question. Do not combine multiple questions in one response.\n"
    "Use Socratic prompts: \"What makes you think that?\", \"Can you tell me more?\", "
    "\"What else?\" Ask one follow-up question only after the student speaks.\n"
    "Use motivational interviewing style by reflecting their words as a question "
    "(\"Tumne kaha X, theek samjha?\"), then ask an open-ended question.\n"
    "Keep responses 1-2 short sentences. Do not summarize or analyze during the session; "
    "all analysis is only for the post-session report.\n"
    "Never label emotions or say \"interesting\", \"good point\", \"I understand\", "
    "or \"that's a valid perspective\". Do not interrupt their thought flow.\n"
    "Be culturally aware of Indian school dynamics and use Hindi naturally: beta, "
    "accha, hmm, theek hai, aur batao.\n\n"
)
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    response = templates.TemplateResponse("live.html", {"request": request})
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
            "model": "gpt-4o-realtime-preview",
            "instructions": COUNSELLOR_INSTRUCTIONS + scenario,
            "audio": {"output": {"voice": "sage"}},
            "input_audio_transcription": {"model": "whisper-1"},
            "turn_detection": {"type": "server_vad", "threshold": 0.5, "silence_duration_ms": 500},
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
    media_type = "application/sdp" if resp.status_code in (200, 201) else "text/plain"
    return Response(content=resp.text, status_code=resp.status_code, media_type=media_type)
@app.post("/api/analyze-session")
async def analyze_session(
    video: UploadFile = File(...),
    transcript: str = Form("[]"),
    student_name: str = Form("Student"),
    student_class: str = Form("10"),
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
    try:
        import profile_generator
        profile = profile_generator.generate_profile(session_data)
        print(f"[analyze] profile keys: {list(profile.keys())}")
        return JSONResponse({"profile": profile, "face_data": face_data, "voice_data": voice_data})
    except Exception as exc:
        print(f"Profile generation failed: {exc}")
        traceback.print_exc()
        return JSONResponse({"profile": {"summary": f"Analysis error: {exc}"}})
    finally:
        os.unlink(tmp.name)
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8501)
