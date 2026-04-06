"""API routes: session analysis and case studies.

The /analyze-session endpoint uses a single unified Gemini call
(unified_analyzer) instead of separate face/voice/profile pipelines.
"""

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import JSONResponse

from counselai.analysis.dashboard_persistence import persist_session_analysis
from counselai.settings import settings
from counselai.storage.db import get_sync_session_factory, init_db
from counselai.storage.models import SessionRecord, Turn

logger = logging.getLogger(__name__)

router = APIRouter()


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

    # DB turns are authoritative when session_id is present
    if session_id:
        db_turns = _load_transcript_turns_from_session(session_id)
        if db_turns:
            transcript_data = db_turns

    if settings.debug:
        try:
            with open("/tmp/counselai_last_transcript.json", "w") as f:
                json.dump(transcript_data, f, indent=2)
        except Exception as exc:
            logger.debug("Failed to save debug transcript: %s", exc)

    # Read video for multimodal analysis (transcript + video in one Gemini call)
    video_bytes = b""
    if video:
        video_bytes = await video.read()

    session_end = session_end_time or datetime.now(timezone.utc).isoformat()

    has_transcripts = len(transcript_data) > 0 and any(
        e.get("text", "").strip() for e in transcript_data
    )

    session_duration = 0
    try:
        if session_start_time and session_end:
            start = datetime.fromisoformat(session_start_time.replace("Z", "+00:00"))
            end = datetime.fromisoformat(session_end.replace("Z", "+00:00"))
            session_duration = (end - start).total_seconds()
    except Exception:
        pass

    has_duration = session_duration > 30

    if not (has_transcripts or has_duration):
        return JSONResponse(
            {"error": "Insufficient session data for analysis."},
            status_code=400,
        )

    # Load observations and case study context from DB if available
    observations_data = []
    segments_data = []
    case_study_text = ""
    if session_id:
        observations_data, segments_data = _load_observations_from_session(session_id)
        case_study_text = _load_case_study_context(session_id)

    # Single unified Gemini call — replaces face_analyzer + voice_analyzer + profile_generator
    analysis_result = {}
    try:
        from counselai.analysis.unified_analyzer import analyze_session as run_analysis

        loop = asyncio.get_running_loop()
        _video = video_bytes if len(video_bytes) > 1000 else None
        _obs = observations_data
        _segs = segments_data
        _case = case_study_text
        analysis_result = await asyncio.wait_for(
            loop.run_in_executor(
                None,
                lambda: run_analysis(
                    transcript_data,
                    student_name=student_name,
                    student_grade=student_class,
                    student_school=student_school,
                    case_study=_case,
                    duration_seconds=int(session_duration),
                    video_bytes=_video,
                    observations=_obs,
                    segments=_segs,
                ),
            ),
            timeout=60,
        )
    except asyncio.TimeoutError:
        logger.warning("Unified analysis timed out after 60s")
        from counselai.analysis.unified_analyzer import _fallback_result
        analysis_result = _fallback_result("Timed out after 60s")
    except Exception as exc:
        logger.error("Unified analysis failed: %s", exc, exc_info=True)
        from counselai.analysis.unified_analyzer import _fallback_result
        analysis_result = _fallback_result(str(exc))

    # Persist to session record
    _persist_analysis_to_session(
        session_id,
        analysis_result,
        student_name=student_name,
        student_grade=student_class,
        student_section=student_section,
        student_school=student_school,
        student_age=student_age,
    )

    # Return in a shape the frontend can render
    # face_data and voice_data now come from the analysis result
    return JSONResponse(
        {
            "profile": analysis_result,
            "face_data": analysis_result.get("face_data", {}),
            "voice_data": analysis_result.get("voice_data", {}),
            "session_id": session_id,
        }
    )


def _load_case_study_context(session_id: str | None) -> str:
    """Load case study scenario text for the session's case_study_id."""
    if not session_id:
        return ""
    try:
        init_db()
        factory = get_sync_session_factory()
        db = factory()
        try:
            sid = uuid.UUID(session_id)
            session = db.get(SessionRecord, sid)
            if session is None or not session.case_study_id:
                return ""
            from case_studies import CASE_STUDIES
            for cs in CASE_STUDIES:
                if cs.get("id") == session.case_study_id:
                    return f"[{cs['id']}] {cs.get('title', '')}: {cs.get('scenario_text', '')}"
            return f"Case study ID: {session.case_study_id}"
        finally:
            db.close()
    except Exception as exc:
        logger.warning("Failed to load case study for session %s: %s", session_id, exc)
        return ""


def _load_observations_from_session(session_id: str | None) -> tuple[list[dict], list[dict]]:
    """Load real-time observations and segments from DB session record."""
    if not session_id:
        return [], []
    try:
        init_db()
        factory = get_sync_session_factory()
        db = factory()
        try:
            sid = uuid.UUID(session_id)
            session = db.get(SessionRecord, sid)
            if session is None:
                return [], []
            observations = session.observations_json or []
            segments = session.segments_json or []
            return observations, segments
        finally:
            db.close()
    except Exception as exc:
        logger.warning("Failed to load observations for session %s: %s", session_id, exc)
        return [], []


def _load_transcript_turns_from_session(session_id: str | None) -> list[dict]:
    """Best-effort fallback to DB turns when the browser submits no transcript."""
    if not session_id:
        return []

    try:
        init_db()
        factory = get_sync_session_factory()
        db = factory()
        try:
            sid = uuid.UUID(session_id)
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


def _persist_analysis_to_session(
    session_id: str | None,
    analysis_result: dict,
    *,
    student_name: str,
    student_grade: str,
    student_section: str,
    student_school: str,
    student_age: int,
) -> None:
    """Save the unified analysis to an existing SessionRecord."""
    if not session_id:
        logger.warning("No session_id provided — analysis not persisted to DB")
        return

    try:
        init_db()
        factory = get_sync_session_factory()
        db = factory()
        try:
            sid = uuid.UUID(session_id)

            # Build dashboard payload from unified analysis
            dashboard_payload = {
                "counsellor_view": {
                    "summary": analysis_result.get("session_summary", ""),
                    "constructs": analysis_result.get("constructs", []),
                    "cross_modal_notes": [],
                    "follow_up": analysis_result.get("follow_up", {}),
                },
                "student_view": analysis_result.get("student_view", {}),
                "school_view": analysis_result.get("school_view", {}),
                "hypotheses": [
                    {
                        "construct_key": c.get("key", ""),
                        "label": c.get("label", ""),
                        "score": c.get("score", 0),
                        "status": c.get("status", "mixed"),
                        "evidence_summary": c.get("evidence_summary", ""),
                    }
                    for c in analysis_result.get("constructs", [])
                ],
                "red_flags": [
                    {"key": f.get("key", ""), "severity": f.get("severity", "medium"), "reason": f.get("reason", "")}
                    for f in analysis_result.get("risk_assessment", {}).get("flags", [])
                ],
            }

            report_data = {
                "profile": analysis_result,
                "profile_raw": analysis_result,
                "face_data": analysis_result.get("face_data", {}),
                "voice_data": analysis_result.get("voice_data", {}),
            }

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
                logger.warning("Session %s not found — cannot persist analysis", session_id)
                return

            db.commit()
            logger.info("Unified analysis persisted to session %s", session_id)
        except Exception as exc:
            db.rollback()
            logger.error("Failed to persist analysis: %s", exc)
        finally:
            db.close()
    except Exception as exc:
        logger.error("Failed to persist analysis (outer): %s", exc)
