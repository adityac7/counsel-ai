"""Legacy API routes: session analysis, case studies.

These routes preserve backward compatibility with the original monolithic app.
They will be migrated to the new pipeline (ingest/canonicalize) in later tasks.
"""

import asyncio
import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import JSONResponse

from counselai.analysis.dashboard_persistence import persist_session_analysis
from counselai.analysis.profile_views import (
    build_dashboard_profile_payload,
    normalize_profile_for_dashboard,
)

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


@router.post("/gemini-transcribe")
async def gemini_transcribe(audio: UploadFile = File(None)):
    """Transcribe student audio using Gemini Flash Lite.

    Called by the frontend every 3 seconds with buffered mic audio.
    Returns clean romanized Hindi/English text.
    """
    if audio is None:
        return JSONResponse({"transcript": ""})

    audio_bytes = await audio.read()
    if len(audio_bytes) < 1000:
        return JSONResponse({"transcript": ""})
    if len(audio_bytes) > 5_000_000:
        return JSONResponse({"transcript": ""}, status_code=413)

    try:
        from counselai.api.audio_utils import transcribe_audio

        text = await asyncio.to_thread(_sync_transcribe, audio_bytes)
        return JSONResponse({"transcript": text})
    except Exception as exc:
        logger.warning("Transcription failed: %s", exc)
        return JSONResponse({"transcript": ""})


def _sync_transcribe(audio_bytes: bytes) -> str:
    """Synchronous wrapper for Gemini transcription (runs in thread pool)."""
    from google.genai import types as gt
    from counselai.api.gemini_client import get_gemini_client, GEMINI_TRANSCRIPTION_MODEL

    client = get_gemini_client()
    response = client.models.generate_content(
        model=GEMINI_TRANSCRIPTION_MODEL,
        contents=[
            "Transcribe the human speech in this audio to text. "
            "The speaker is an Indian student speaking Hindi, Hinglish, or English. "
            "Return ONLY the spoken words in ROMAN script (Latin alphabet). "
            "Hindi words should be romanized: 'accha' not 'अच्छा'. "
            "If there is no clear speech, return an empty string.",
            gt.Part.from_bytes(data=audio_bytes, mime_type="audio/wav"),
        ],
        config=gt.GenerateContentConfig(),
    )
    text = (response.text or "").strip()
    skip = {"silence", "no speech", "no clear speech", "no audio", "no words", "empty"}
    if any(s in text.lower() for s in skip) and len(text) < 50:
        return ""
    return text


@router.get("/case-studies")
async def get_case_studies():
    from case_studies import CASE_STUDIES
    return JSONResponse({"case_studies": CASE_STUDIES})


@router.post("/analyze-session")
async def analyze_session(
    video: UploadFile | None = File(None),
    transcript: str = Form("[]"),
    student_name: str = Form("Student"),
    student_class: str = Form("10"),
    student_section: str = Form(""),
    student_school: str = Form(""),
    student_age: int = Form(15),
    session_start_time: str = Form(None),
    session_end_time: str = Form(None),
    session_id: str = Form(None),
):
    try:
        transcript_data = json.loads(transcript)
    except (json.JSONDecodeError, TypeError):
        transcript_data = []

    if session_id and not any(
        isinstance(entry, dict) and entry.get("text", "").strip()
        for entry in transcript_data
    ):
        transcript_data = _load_transcript_turns_from_session(session_id) or transcript_data

    if os.environ.get("COUNSELAI_DEBUG"):
        try:
            with open("/tmp/counselai_last_transcript.json", "w") as f:
                json.dump(transcript_data, f, indent=2)
        except Exception as exc:
            logger.debug("Failed to save debug transcript: %s", exc)

    video_bytes = (await video.read()) if video else b""
    has_video_file = len(video_bytes) > 1000  # skip tiny/empty uploads

    tmp = None
    if has_video_file:
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".webm")
        tmp.write(video_bytes)
        tmp.close()
    else:
        logger.info("Video empty or missing (%d bytes) — skipping AV analysis", len(video_bytes))

    face_data, voice_data = {}, {}
    if tmp:
        try:
            from counselai.analysis.face_analyzer import analyze_frames
            from counselai.api.media_utils import save_frames_from_video

            frames_dir = tempfile.mkdtemp()
            save_frames_from_video(tmp.name, frames_dir, interval=3)
            face_data = analyze_frames(frames_dir)
        except Exception as exc:
            logger.info("Face analysis skipped: %s", exc)

        try:
            from counselai.api.media_utils import extract_audio_from_video
            from counselai.analysis.voice_analyzer import analyze_audio

            audio_path = extract_audio_from_video(tmp.name)
            if audio_path:
                voice_data = analyze_audio(audio_path)
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

    raw_profile = {}
    try:
        from counselai.analysis.profile_generator import generate_profile

        loop = asyncio.get_running_loop()
        raw_profile = await asyncio.wait_for(
            loop.run_in_executor(
                None,
                generate_profile,
                {
                    "student_info": {"name": student_name, "class": student_class},
                    "rounds": [
                        {"transcription": e.get("text", ""), "role": e.get("role", "student")}
                        for e in transcript_data
                    ],
                    "face_data": face_data,
                    "voice_data": voice_data,
                },
            ),
            timeout=45,
        )
    except asyncio.TimeoutError:
        logger.warning("Profile generation timed out after 45s")
        raw_profile = {"summary": "Profile generation timed out. Partial results may be available."}
    except Exception as exc:
        logger.error("Profile generation failed: %s", exc, exc_info=True)
        raw_profile = {"summary": "Profile generation encountered an error. Please try again."}
    finally:
        if tmp:
            os.unlink(tmp.name)

    sanitized_profile = _sanitize(raw_profile)
    normalized_profile = normalize_profile_for_dashboard(sanitized_profile) or {}
    dashboard_payload = build_dashboard_profile_payload(
        sanitized_profile,
        normalized_profile=normalized_profile,
    )

    # Persist profile + analysis to the existing session record (if session_id provided)
    report_data = {
        "profile": normalized_profile,
        "profile_raw": sanitized_profile,
        "face_data": _sanitize(face_data),
        "voice_data": _sanitize(voice_data),
        "duration_seconds": int(session_duration) if session_duration else None,
    }
    _persist_report_to_session(
        session_id,
        report_data,
        dashboard_payload=dashboard_payload,
        student_name=student_name,
        student_grade=student_class,
        student_section=student_section,
        student_school=student_school,
        student_age=student_age,
    )

    return JSONResponse(
        {
            "profile": _sanitize(raw_profile),
            "face_data": _sanitize(face_data),
            "voice_data": _sanitize(voice_data),
            "session_id": session_id,
        }
    )


def _load_transcript_turns_from_session(session_id: str | None) -> list[dict]:
    """Best-effort fallback to DB turns when the browser submits no transcript."""
    if not session_id:
        return []

    try:
        import uuid as _uuid
        from counselai.storage.db import get_sync_session_factory, init_db
        from counselai.storage.models import Turn

        init_db()
        factory = get_sync_session_factory()
        db = factory()
        try:
            sid = _uuid.UUID(session_id)
            turns = (
                db.query(Turn)
                .filter(Turn.session_id == sid)
                .order_by(Turn.turn_index.asc())
                .all()
            )
            return [
                {"role": t.speaker, "text": t.text}
                for t in turns
                if t.text and t.text.strip()
            ]
        finally:
            db.close()
    except Exception as exc:
        logger.warning("Failed to load fallback transcript for session %s: %s", session_id, exc)
        return []


def _persist_report_to_session(
    session_id: str | None,
    report_data: dict,
    *,
    dashboard_payload: dict,
    student_name: str,
    student_grade: str,
    student_section: str,
    student_school: str,
    student_age: int,
) -> None:
    """Save the analysis report to an existing SessionRecord.

    Updates the session's `report` JSON column and dashboard-facing rows.
    Session timing is finalized by the live websocket lifecycle.
    """
    if not session_id:
        logger.warning("No session_id provided — report not persisted to DB")
        return

    try:
        import uuid as _uuid
        from counselai.storage.db import get_sync_session_factory, init_db

        init_db()
        factory = get_sync_session_factory()
        db = factory()
        try:
            sid = _uuid.UUID(session_id)
            persisted = persist_session_analysis(
                db,
                session_id=sid,
                report_data=report_data,
                dashboard_payload=dashboard_payload,
                student_name=student_name,
                student_grade=student_grade,
                student_section=student_section,
                student_school=student_school,
                student_age=student_age,
            )
            if not persisted:
                logger.warning(
                    "Session %s not found — cannot persist analysis artifacts",
                    session_id,
                )
                return

            db.commit()
            logger.info("Analysis artifacts persisted to session %s", session_id)
        except Exception as exc:
            db.rollback()
            logger.error("Failed to persist analysis artifacts: %s", exc)
        finally:
            db.close()
    except Exception as exc:
        logger.error("Failed to persist report (outer): %s", exc)
