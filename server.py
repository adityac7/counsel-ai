from fastapi import FastAPI, UploadFile, File, Form
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse
from dotenv import load_dotenv
import json, os, tempfile, uuid

load_dotenv()

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")

# In-memory session store
sessions = {}

from case_studies import CASE_STUDIES
from counsellor import CounsellorSession
import transcriber, face_analyzer, voice_analyzer, profile_generator, utils


@app.get("/", response_class=HTMLResponse)
async def index():
    with open("templates/index.html") as f:
        return f.read()


@app.get("/api/case-studies")
async def get_case_studies():
    return CASE_STUDIES


@app.post("/api/session/start")
async def start_session(
    name: str = Form(...),
    student_class: str = Form(...),
    section: str = Form(""),
    school: str = Form(""),
    age: int = Form(15),
):
    sid = str(uuid.uuid4())
    # pick first case study matching class
    class_int = int(student_class)
    case = next(
        (
            c
            for c in CASE_STUDIES
            if str(class_int) in str(c.get("target_class", "9-10-11-12"))
        ),
        CASE_STUDIES[0],
    )
    student_info = {
        "name": name,
        "class": student_class,
        "section": section,
        "school": school,
        "age": age,
    }
    counsellor_session = CounsellorSession(case_study=case, student_info=student_info)
    sessions[sid] = {
        "student_info": student_info,
        "case_study": case,
        "counsellor": counsellor_session,
        "rounds": [],
        "current_round": 0,
    }
    return {"session_id": sid, "case_study": case}


@app.post("/api/session/{sid}/respond")
async def respond(
    sid: str,
    text: str = Form(None),
    audio: UploadFile = File(None),
    video: UploadFile = File(None),
):
    if sid not in sessions:
        return JSONResponse({"error": "Session not found"}, 404)

    session = sessions[sid]
    session["current_round"] += 1
    round_num = session["current_round"]

    transcription = ""
    face_data = {}
    voice_data = {}

    if text:
        transcription = text

    if audio:
        # Save audio, transcribe
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".webm")
        tmp.write(await audio.read())
        tmp.close()
        try:
            result = transcriber.transcribe_audio(tmp.name)
            transcription = result.get("text", "") if isinstance(result, dict) else str(result)
        except Exception as e:
            transcription = text or f"[Transcription failed: {e}]"

        # Voice analysis
        try:
            audio_path = utils.extract_audio_from_video(tmp.name) if video else tmp.name
            voice_data = voice_analyzer.analyze_audio(audio_path)
        except:
            pass
        os.unlink(tmp.name)

    if video:
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".webm")
        tmp.write(await video.read())
        tmp.close()
        try:
            frames_dir = tempfile.mkdtemp()
            utils.save_frames_from_video(tmp.name, frames_dir, interval=2)
            face_data = face_analyzer.analyze_frames(frames_dir)
        except:
            pass
        os.unlink(tmp.name)

    # Get counsellor response
    response_text = session["counsellor"].add_response(
        round_num, transcription, face_data, voice_data
    )

    session["rounds"].append(
        {
            "round": round_num,
            "transcription": transcription,
            "face_data": face_data,
            "voice_data": voice_data,
            "counsellor_response": response_text,
        }
    )

    return {
        "round": round_num,
        "transcription": transcription,
        "counsellor_response": response_text,
        "face_summary": face_data.get("summary", {}),
        "voice_summary": voice_data.get("speech_rate", {}),
    }


@app.post("/api/session/{sid}/profile")
async def generate_profile(sid: str):
    if sid not in sessions:
        return JSONResponse({"error": "Session not found"}, 404)
    session = sessions[sid]
    context = session["counsellor"].get_all_context()
    profile = profile_generator.generate_profile(context)
    cross = profile_generator.cross_validate(context, profile)
    return {"profile": profile, "cross_validation": cross}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8501)
