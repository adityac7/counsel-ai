"""Session canonicalizer — the main ingestion entry point.

Converts raw browser output (media bytes, transcript events, metadata)
into:
  1. Canonical artifact files on disk (session.json, turns.jsonl, media files)
  2. Database rows (sessions, turns, artifacts tables)

Handles partial failures gracefully: if media write fails, transcript
and session metadata are still persisted so recovery is possible.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Sequence

from sqlalchemy.orm import Session as DBSession

from counselai.ingest.artifact_store import ArtifactStore
from counselai.ingest.manifest import ManifestBuilder
from counselai.settings import settings
from counselai.storage.models import (
    ArtifactType,
    SessionRecord,
    SessionStatus,
    Speaker,
    TranscriptSource,
)
from counselai.storage.repositories.sessions import SessionRepository

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes for raw ingestion input
# ---------------------------------------------------------------------------

class RawTurn:
    """A single transcript turn from the browser."""

    __slots__ = ("turn_index", "speaker", "start_ms", "end_ms", "text", "source", "confidence")

    def __init__(
        self,
        *,
        turn_index: int,
        speaker: str,
        start_ms: int,
        end_ms: int,
        text: str,
        source: str = "live_transcript",
        confidence: float | None = None,
    ) -> None:
        self.turn_index = turn_index
        self.speaker = speaker
        self.start_ms = start_ms
        self.end_ms = end_ms
        self.text = text
        self.source = source
        self.confidence = confidence

    def to_dict(self) -> dict[str, Any]:
        return {
            "turn_index": self.turn_index,
            "speaker": self.speaker,
            "start_ms": self.start_ms,
            "end_ms": self.end_ms,
            "text": self.text,
            "source": self.source,
            "confidence": self.confidence,
        }


# ---------------------------------------------------------------------------
# Canonicalizer
# ---------------------------------------------------------------------------

class SessionCanonicalizer:
    """Orchestrates the ingestion of a single session's raw data."""

    def __init__(self, db: DBSession, store: ArtifactStore | None = None) -> None:
        self.db = db
        self.repo = SessionRepository(db)
        self.store = store or ArtifactStore()

    # -- Public API ---------------------------------------------------------

    def create_session(
        self,
        *,
        student_id: uuid.UUID,
        case_study_id: str,
        provider: str,
        primary_language: str | None = None,
    ) -> SessionRecord:
        """Create a draft session record and initialize its artifact directory."""
        session = self.repo.create(
            student_id=student_id,
            case_study_id=case_study_id,
            provider=provider,
            status=SessionStatus.draft,
            primary_language=primary_language,
            processing_version=settings.processing_version,
        )
        # Ensure artifact directory exists
        self.store.session_dir(str(session.id))
        logger.info("Created session %s (student=%s, case=%s)", session.id, student_id, case_study_id)
        self.db.commit()
        return session

    def ingest_turns(
        self,
        session_id: uuid.UUID,
        raw_turns: Sequence[RawTurn],
    ) -> int:
        """Persist transcript turns to both DB and turns.jsonl artifact.

        Returns the number of turns ingested.
        """
        sid = str(session_id)
        turn_dicts: list[dict] = []

        for rt in raw_turns:
            # DB row
            self.repo.add_turn(
                session_id,
                turn_index=rt.turn_index,
                speaker=Speaker(rt.speaker),
                start_ms=rt.start_ms,
                end_ms=rt.end_ms,
                text=rt.text,
                source=TranscriptSource(rt.source),
                confidence=rt.confidence,
            )
            turn_dicts.append(rt.to_dict())

        # Write turns.jsonl artifact
        if turn_dicts:
            path, sha = self.store.write_jsonl(sid, "turns.jsonl", turn_dicts)
            self.repo.add_artifact(
                session_id,
                artifact_type=ArtifactType.transcript_canonical,
                storage_uri=self.store.uri(sid, "turns.jsonl"),
                sha256=sha,
                metadata_json={"turn_count": len(turn_dicts)},
            )

        self.db.flush()
        logger.info("Ingested %d turns for session %s", len(turn_dicts), session_id)
        return len(turn_dicts)

    def ingest_audio(
        self,
        session_id: uuid.UUID,
        audio_bytes: bytes,
        *,
        filename: str = "audio.raw.webm",
        mime_type: str = "audio/webm",
    ) -> str | None:
        """Persist raw audio artifact. Returns storage URI or None on failure."""
        sid = str(session_id)
        try:
            path, sha = self.store.write_bytes(sid, filename, audio_bytes)
            self.repo.add_artifact(
                session_id,
                artifact_type=ArtifactType.audio_raw,
                storage_uri=self.store.uri(sid, filename),
                sha256=sha,
                metadata_json={"mime_type": mime_type, "size_bytes": len(audio_bytes)},
            )
            self.db.flush()
            logger.info("Stored audio artifact for session %s (%d bytes)", session_id, len(audio_bytes))
            return self.store.uri(sid, filename)
        except Exception:
            logger.exception("Failed to store audio for session %s", session_id)
            return None

    def ingest_video(
        self,
        session_id: uuid.UUID,
        video_bytes: bytes,
        *,
        filename: str = "video.raw.webm",
        mime_type: str = "video/webm",
    ) -> str | None:
        """Persist raw video artifact. Returns storage URI or None on failure."""
        sid = str(session_id)
        try:
            path, sha = self.store.write_bytes(sid, filename, video_bytes)
            self.repo.add_artifact(
                session_id,
                artifact_type=ArtifactType.video_raw,
                storage_uri=self.store.uri(sid, filename),
                sha256=sha,
                metadata_json={"mime_type": mime_type, "size_bytes": len(video_bytes)},
            )
            self.db.flush()
            logger.info("Stored video artifact for session %s (%d bytes)", session_id, len(video_bytes))
            return self.store.uri(sid, filename)
        except Exception:
            logger.exception("Failed to store video for session %s", session_id)
            return None

    def finalize_session(
        self,
        session_id: uuid.UUID,
        *,
        raw_turns: Sequence[RawTurn] | None = None,
        audio_bytes: bytes | None = None,
        video_bytes: bytes | None = None,
        extra_metadata: dict[str, Any] | None = None,
    ) -> SessionRecord | None:
        """Complete ingestion: persist all artifacts, write manifest, update status.

        This is the main entry point for post-session ingestion. It:
        1. Persists turns (if provided and not already ingested)
        2. Persists audio/video media
        3. Builds and writes session.json manifest
        4. Transitions session to 'uploaded' status
        5. Commits the transaction

        Returns the updated SessionRecord, or None if session not found.
        Browser failures still leave a recoverable partial record because
        each sub-step is flushed independently.
        """
        session = self.repo.get(session_id)
        if session is None:
            logger.error("Session %s not found for finalization", session_id)
            return None

        sid = str(session_id)
        now = datetime.now(timezone.utc)

        # -- Ingest turns ---------------------------------------------------
        turn_count = 0
        if raw_turns:
            turn_count = self.ingest_turns(session_id, raw_turns)

        # -- Ingest media (best-effort) -------------------------------------
        if audio_bytes:
            self.ingest_audio(session_id, audio_bytes)

        if video_bytes:
            self.ingest_video(session_id, video_bytes)

        # -- Build manifest -------------------------------------------------
        builder = ManifestBuilder(self.store, sid)
        builder.set_session_meta(
            student_id=str(session.student_id),
            case_study_id=session.case_study_id,
            provider=session.provider,
            status="uploaded",
            started_at=session.started_at.isoformat() if session.started_at else "",
            primary_language=session.primary_language,
            processing_version=session.processing_version or settings.processing_version,
        )

        # Add references to all artifacts we just stored
        artifacts = self.repo.get_artifacts(session_id)
        for art in artifacts:
            builder.add_artifact(
                artifact_type=art.artifact_type.value,
                storage_uri=art.storage_uri,
                sha256=art.sha256,
                metadata=art.metadata_json,
            )

        # Compute duration
        duration_seconds: int | None = None
        if session.started_at:
            duration_seconds = int((now - session.started_at).total_seconds())

        manifest = builder.build(
            ended_at=now.isoformat(),
            duration_seconds=duration_seconds,
            turn_count=turn_count,
            status="uploaded",
        )
        manifest_uri = builder.save(manifest)

        # -- Update session record ------------------------------------------
        session.status = SessionStatus.uploaded
        session.ended_at = now
        session.duration_seconds = duration_seconds
        session.artifact_manifest_path = manifest_uri

        if extra_metadata and extra_metadata.get("primary_language"):
            session.primary_language = extra_metadata["primary_language"]

        self.db.commit()
        logger.info(
            "Finalized session %s: %d turns, status=%s, manifest=%s",
            session_id, turn_count, session.status.value, manifest_uri,
        )
        return session

    def mark_processing(self, session_id: uuid.UUID) -> SessionRecord | None:
        """Transition session to 'processing' status."""
        session = self.repo.update_status(session_id, SessionStatus.processing)
        if session:
            self.db.commit()
        return session

    def mark_failed(self, session_id: uuid.UUID, *, reason: str = "") -> SessionRecord | None:
        """Transition session to 'failed' status, preserving partial artifacts."""
        session = self.repo.update_status(session_id, SessionStatus.failed)
        if session:
            # Write a failure marker so downstream tools know why
            self.store.write_json(str(session_id), "_failure.json", {
                "reason": reason,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            self.db.commit()
            logger.warning("Session %s marked as failed: %s", session_id, reason)
        return session
