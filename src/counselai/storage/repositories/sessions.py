"""Repository for session CRUD and related queries."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from counselai.storage.models import (
    Artifact,
    ArtifactType,
    SessionRecord,
    SessionStatus,
    Turn,
    Speaker,
    TranscriptSource,
)


class SessionRepository:
    """Encapsulates all session-related database operations."""

    def __init__(self, db: Session) -> None:
        self.db = db

    # -- Session CRUD -------------------------------------------------------

    def create(
        self,
        *,
        student_id: uuid.UUID,
        case_study_id: str,
        provider: str,
        status: SessionStatus = SessionStatus.draft,
        primary_language: str | None = None,
        processing_version: str | None = None,
    ) -> SessionRecord:
        session = SessionRecord(
            student_id=student_id,
            case_study_id=case_study_id,
            provider=provider,
            status=status,
            primary_language=primary_language,
            processing_version=processing_version,
        )
        self.db.add(session)
        self.db.flush()
        return session

    def get(self, session_id: uuid.UUID) -> SessionRecord | None:
        return self.db.get(SessionRecord, session_id)

    def get_with_relations(self, session_id: uuid.UUID) -> SessionRecord | None:
        stmt = (
            select(SessionRecord)
            .where(SessionRecord.id == session_id)
            .options(
                joinedload(SessionRecord.turns),
                joinedload(SessionRecord.artifacts),
                joinedload(SessionRecord.profiles),
            )
        )
        return self.db.execute(stmt).unique().scalar_one_or_none()

    def list_by_student(
        self, student_id: uuid.UUID, *, limit: int = 50
    ) -> Sequence[SessionRecord]:
        stmt = (
            select(SessionRecord)
            .where(SessionRecord.student_id == student_id)
            .order_by(SessionRecord.started_at.desc())
            .limit(limit)
        )
        return self.db.execute(stmt).scalars().all()

    def list_by_status(
        self, status: SessionStatus, *, limit: int = 100
    ) -> Sequence[SessionRecord]:
        stmt = (
            select(SessionRecord)
            .where(SessionRecord.status == status)
            .order_by(SessionRecord.started_at.desc())
            .limit(limit)
        )
        return self.db.execute(stmt).scalars().all()

    def update_status(
        self,
        session_id: uuid.UUID,
        status: SessionStatus,
        *,
        ended_at: datetime | None = None,
        duration_seconds: int | None = None,
    ) -> SessionRecord | None:
        session = self.get(session_id)
        if session is None:
            return None
        session.status = status
        if ended_at is not None:
            session.ended_at = ended_at
        if duration_seconds is not None:
            session.duration_seconds = duration_seconds
        self.db.flush()
        return session

    def complete(self, session_id: uuid.UUID) -> SessionRecord | None:
        """Mark session as completed with end timestamp and computed duration."""
        session = self.get(session_id)
        if session is None:
            return None
        now = datetime.now(timezone.utc)
        session.status = SessionStatus.completed
        session.ended_at = now
        if session.started_at:
            session.duration_seconds = int(
                (now - session.started_at).total_seconds()
            )
        self.db.flush()
        return session

    # -- Turns --------------------------------------------------------------

    def add_turn(
        self,
        session_id: uuid.UUID,
        *,
        turn_index: int,
        speaker: Speaker,
        start_ms: int,
        end_ms: int,
        text: str,
        source: TranscriptSource = TranscriptSource.live_transcript,
        confidence: float | None = None,
    ) -> Turn:
        turn = Turn(
            session_id=session_id,
            turn_index=turn_index,
            speaker=speaker,
            start_ms=start_ms,
            end_ms=end_ms,
            text=text,
            source=source,
            confidence=confidence,
        )
        self.db.add(turn)
        self.db.flush()
        return turn

    def get_turns(self, session_id: uuid.UUID) -> Sequence[Turn]:
        stmt = (
            select(Turn)
            .where(Turn.session_id == session_id)
            .order_by(Turn.turn_index)
        )
        return self.db.execute(stmt).scalars().all()

    # -- Artifacts ----------------------------------------------------------

    def add_artifact(
        self,
        session_id: uuid.UUID,
        *,
        artifact_type: ArtifactType,
        storage_uri: str,
        sha256: str,
        metadata_json: dict | None = None,
    ) -> Artifact:
        artifact = Artifact(
            session_id=session_id,
            artifact_type=artifact_type,
            storage_uri=storage_uri,
            sha256=sha256,
            metadata_json=metadata_json or {},
        )
        self.db.add(artifact)
        self.db.flush()
        return artifact

    def get_artifacts(
        self, session_id: uuid.UUID, artifact_type: ArtifactType | None = None
    ) -> Sequence[Artifact]:
        stmt = select(Artifact).where(Artifact.session_id == session_id)
        if artifact_type is not None:
            stmt = stmt.where(Artifact.artifact_type == artifact_type)
        stmt = stmt.order_by(Artifact.created_at)
        return self.db.execute(stmt).scalars().all()
