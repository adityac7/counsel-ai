"""Live session API routes.

POST /session           — Create a session record before media starts.
POST /session/{id}/upload — Upload raw media and transcript after session ends.
POST /session/{id}/complete — Mark upload complete and enqueue analysis.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from counselai.api.deps import get_db
from counselai.api.schemas import (
    SessionCompleteResponse,
    SessionCreateRequest,
    SessionCreateResponse,
    SessionStatus,
)
from counselai.ingest.artifact_store import ArtifactStore
from counselai.ingest.canonicalizer import RawTurn, SessionCanonicalizer
from counselai.storage.models import SessionStatus as DBSessionStatus

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_canonicalizer(db: Session) -> SessionCanonicalizer:
    return SessionCanonicalizer(db)


def _parse_turns(transcript_json: str) -> list[RawTurn]:
    """Parse a JSON array of turn objects from the browser into RawTurn list."""
    try:
        raw = json.loads(transcript_json) if transcript_json else []
    except (json.JSONDecodeError, TypeError):
        raw = []

    turns: list[RawTurn] = []
    for i, entry in enumerate(raw):
        # Support both structured turns and legacy {text, role} format
        text = entry.get("text", "").strip()
        if not text:
            continue
        turns.append(RawTurn(
            turn_index=entry.get("turn_index", i),
            speaker=entry.get("speaker", entry.get("role", "student")),
            start_ms=entry.get("start_ms", 0),
            end_ms=entry.get("end_ms", 0),
            text=text,
            source=entry.get("source", "live_transcript"),
            confidence=entry.get("confidence"),
        ))
    return turns


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/session", response_model=SessionCreateResponse)
def create_session(body: SessionCreateRequest, db: Session = Depends(get_db)):
    """Create a session record before media starts."""
    canon = _get_canonicalizer(db)
    try:
        session = canon.create_session(
            student_id=body.student_id,
            case_study_id=body.case_study_id,
            provider=body.provider,
        )
        return SessionCreateResponse(
            session_id=session.id,
            status=SessionStatus.draft,
        )
    except Exception as exc:
        logger.exception("Failed to create session")
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/session/{session_id}/upload")
def upload_session_artifacts(
    session_id: str,
    db: Session = Depends(get_db),
    transcript: str = Form("[]"),
    audio: UploadFile | None = File(None),
    video: UploadFile | None = File(None),
    primary_language: str = Form(""),
):
    """Upload raw media and transcript after session ends.

    Accepts multipart form with:
    - transcript: JSON array of turn objects
    - audio: raw audio file (webm/wav)
    - video: raw video file (webm)
    - primary_language: detected language code
    """
    try:
        sid = uuid.UUID(session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid session_id format")

    canon = _get_canonicalizer(db)

    # Parse turns
    raw_turns = _parse_turns(transcript)

    # Read media bytes
    audio_bytes = audio.file.read() if audio else None
    video_bytes = video.file.read() if video else None

    extra_metadata = {}
    if primary_language:
        extra_metadata["primary_language"] = primary_language

    session = canon.finalize_session(
        sid,
        raw_turns=raw_turns,
        audio_bytes=audio_bytes,
        video_bytes=video_bytes,
        extra_metadata=extra_metadata,
    )

    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    return {
        "session_id": str(session.id),
        "status": session.status.value,
        "turn_count": len(raw_turns),
        "artifacts_stored": True,
    }


@router.post("/session/{session_id}/complete", response_model=SessionCompleteResponse)
def complete_session(session_id: str, db: Session = Depends(get_db)):
    """Mark upload complete and transition to processing.

    This endpoint is called after /upload has persisted all artifacts.
    It transitions the session to 'processing' status and returns a
    job_id for tracking the analysis pipeline.
    """
    try:
        sid = uuid.UUID(session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid session_id format")

    canon = _get_canonicalizer(db)
    session = canon.mark_processing(sid)

    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    # Generate a job_id for the processing pipeline (Task 15 will wire
    # this to Dramatiq/worker queues — for now return a tracking UUID)
    job_id = uuid.uuid4()

    return SessionCompleteResponse(
        session_id=session.id,
        status=SessionStatus.processing,
        job_id=job_id,
    )
