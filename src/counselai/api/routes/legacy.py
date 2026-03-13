"""Legacy API routes: RTC connect, session analysis, case studies.

These routes preserve backward compatibility with the original monolithic app.
They will be migrated to the new pipeline (ingest/canonicalize) in later tasks.
"""

import json
import logging
import os
import tempfile
import traceback
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from fastapi import APIRouter, File, Form, Request, Response, UploadFile
from fastapi.responses import JSONResponse

from counselai.api.constants import COUNSELLOR_INSTRUCTIONS
from counselai.api.exceptions import InsufficientSessionData

logger = logging.getLogger(__name__)

# Project root for legacy module imports
_PROJECT_ROOT = Path(__file__).resolve().parents[4]

router = APIRouter()


def _sanitize(obj):
    """Recursively convert numpy types to native Python for JSON."""
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize(v) for v in obj]
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    return obj


@router.get("/case-studies")
async def get_case_studies():
    from case_studies import CASE_STUDIES
    return JSONResponse({"case_studies": CASE_STUDIES})


@router.post("/rtc-connect")
async def rtc_connect(request: Request):
    import httpx

    openai_key = os.environ.get("OPENAI_API_KEY", "")
    if not openai_key:
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
            headers={"Authorization": f"Bearer {openai_key}"},
            files=[
                ("sdp", (None, sdp_offer, "application/sdp")),
                ("session", (None, session_json, "application/json")),
            ],
        )
    if resp.status_code not in (200, 201):
        request_id = resp.headers.get("x-request-id", "")
        body_preview = resp.text[:1200]
        logger.warning(
            "OpenAI realtime call failed status=%s request_id=%s body=%s",
            resp.status_code, request_id, body_preview,
        )
    media_type = "application/sdp" if resp.status_code in (200, 201) else "text/plain"
    return Response(content=resp.text, status_code=resp.status_code, media_type=media_type)


@router.post("/analyze-session")
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
    import db

    try:
        transcript_data = json.loads(transcript)
    except (json.JSONDecodeError, TypeError):
        transcript_data = []

    if os.environ.get("COUNSELAI_DEBUG"):
        try:
            with open("/tmp/counselai_last_transcript.json", "w") as f:
                json.dump(transcript_data, f, indent=2)
        except Exception as exc:
            logger.debug("Failed to save debug transcript: %s", exc)

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
        logger.info("Face analysis skipped: %s", exc)

    try:
        import utils
        import voice_analyzer

        audio_path = utils.extract_audio_from_video(tmp.name)
        if audio_path:
            voice_data = voice_analyzer.analyze_audio(audio_path)
    except Exception as exc:
        logger.info("Voice analysis skipped: %s", exc)

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
            status_code=400,
        )

    student_info = {
        "name": student_name,
        "class": student_class,
        "section": student_section,
        "school": student_school,
        "age": student_age,
    }

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
            student_info=student_info,
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
        logger.error("Profile generation failed: %s", exc, exc_info=True)
        profile = {"summary": f"Analysis error: {exc}"}
        saved_id = db.save_session(
            source="realtime",
            external_session_id=None,
            student_info=student_info,
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


@router.get("/sessions")
async def get_sessions():
    import db
    return JSONResponse({"sessions": db.list_sessions()})


@router.get("/sessions/{session_id}")
async def get_session_detail(session_id: int):
    import db
    session = db.get_session(session_id)
    if not session:
        return JSONResponse({"error": "Session not found"}, status_code=404)
    return JSONResponse(session)
