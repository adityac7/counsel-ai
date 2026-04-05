"""Async repository for session CRUD with filtering and pagination."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from counselai.storage.models import (
    SessionFeedback,
    SessionRecord,
    SessionStatus,
    Speaker,
    TranscriptSource,
    Turn,
)


class SessionRepository:
    """Async session CRUD with filtering, pagination, and related entities."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # -- Session CRUD -------------------------------------------------------

    async def create(
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
            status=status.value,
            primary_language=primary_language,
            processing_version=processing_version,
        )
        self.db.add(session)
        await self.db.flush()
        return session

    async def get(self, session_id: uuid.UUID) -> SessionRecord | None:
        return await self.db.get(SessionRecord, session_id)

    async def get_with_relations(self, session_id: uuid.UUID) -> SessionRecord | None:
        stmt = (
            select(SessionRecord)
            .where(SessionRecord.id == session_id)
            .options(
                joinedload(SessionRecord.turns),
                joinedload(SessionRecord.profiles),
                joinedload(SessionRecord.feedback),
            )
        )
        result = await self.db.execute(stmt)
        return result.unique().scalar_one_or_none()

    async def list_sessions(
        self,
        *,
        student_id: uuid.UUID | None = None,
        status: SessionStatus | None = None,
        risk_level: str | None = None,
        follow_up_needed: bool | None = None,
        started_after: datetime | None = None,
        started_before: datetime | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[Sequence[SessionRecord], int]:
        """List sessions with optional filters. Returns (rows, total_count)."""
        stmt = select(SessionRecord)
        count_stmt = select(func.count(SessionRecord.id))

        # Apply filters to both
        if student_id is not None:
            stmt = stmt.where(SessionRecord.student_id == student_id)
            count_stmt = count_stmt.where(SessionRecord.student_id == student_id)
        if status is not None:
            stmt = stmt.where(SessionRecord.status == status.value)
            count_stmt = count_stmt.where(SessionRecord.status == status.value)
        if risk_level is not None:
            stmt = stmt.where(SessionRecord.risk_level == risk_level)
            count_stmt = count_stmt.where(SessionRecord.risk_level == risk_level)
        if follow_up_needed is not None:
            stmt = stmt.where(SessionRecord.follow_up_needed == follow_up_needed)
            count_stmt = count_stmt.where(SessionRecord.follow_up_needed == follow_up_needed)
        if started_after is not None:
            stmt = stmt.where(SessionRecord.started_at >= started_after)
            count_stmt = count_stmt.where(SessionRecord.started_at >= started_after)
        if started_before is not None:
            stmt = stmt.where(SessionRecord.started_at <= started_before)
            count_stmt = count_stmt.where(SessionRecord.started_at <= started_before)

        stmt = stmt.order_by(SessionRecord.started_at.desc()).offset(offset).limit(limit)

        result = await self.db.execute(stmt)
        rows = result.scalars().all()

        count_result = await self.db.execute(count_stmt)
        total = count_result.scalar() or 0

        return rows, total

    async def update_status(
        self,
        session_id: uuid.UUID,
        status: SessionStatus,
        *,
        ended_at: datetime | None = None,
        duration_seconds: int | None = None,
    ) -> SessionRecord | None:
        session = await self.get(session_id)
        if session is None:
            return None
        session.status = status.value
        if ended_at is not None:
            session.ended_at = ended_at
        if duration_seconds is not None:
            session.duration_seconds = duration_seconds
        await self.db.flush()
        return session

    async def update_analysis(
        self,
        session_id: uuid.UUID,
        *,
        session_summary: str | None = None,
        risk_level: str | None = None,
        follow_up_needed: bool | None = None,
        topics_discussed: list[str] | None = None,
        student_mood_start: str | None = None,
        student_mood_end: str | None = None,
        turn_count: int | None = None,
    ) -> SessionRecord | None:
        """Update post-analysis fields on a session."""
        session = await self.get(session_id)
        if session is None:
            return None
        if session_summary is not None:
            session.session_summary = session_summary
        if risk_level is not None:
            session.risk_level = risk_level
        if follow_up_needed is not None:
            session.follow_up_needed = follow_up_needed
        if topics_discussed is not None:
            session.topics_discussed = topics_discussed
        if student_mood_start is not None:
            session.student_mood_start = student_mood_start
        if student_mood_end is not None:
            session.student_mood_end = student_mood_end
        if turn_count is not None:
            session.turn_count = turn_count
        await self.db.flush()
        return session

    async def complete(self, session_id: uuid.UUID) -> SessionRecord | None:
        """Mark session as completed with end timestamp and computed duration."""
        session = await self.get(session_id)
        if session is None:
            return None
        now = datetime.now(timezone.utc)
        session.status = SessionStatus.completed.value
        session.ended_at = now
        if session.started_at:
            session.duration_seconds = int((now - session.started_at).total_seconds())
        await self.db.flush()
        return session

    async def delete(self, session_id: uuid.UUID) -> bool:
        """Delete a session and all cascaded children. Returns True if found."""
        session = await self.get(session_id)
        if session is None:
            return False
        await self.db.delete(session)
        await self.db.flush()
        return True

    # -- Turns --------------------------------------------------------------

    async def add_turn(
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
            speaker=speaker.value,
            start_ms=start_ms,
            end_ms=end_ms,
            text=text,
            source=source.value,
            confidence=confidence,
        )
        self.db.add(turn)
        await self.db.flush()
        return turn

    async def get_turns(self, session_id: uuid.UUID) -> Sequence[Turn]:
        stmt = (
            select(Turn)
            .where(Turn.session_id == session_id)
            .order_by(Turn.turn_index)
        )
        result = await self.db.execute(stmt)
        return result.scalars().all()

    # -- Feedback -----------------------------------------------------------

    async def add_feedback(
        self,
        session_id: uuid.UUID,
        *,
        respondent: str = "student",
        rating: int | None = None,
        helpful: bool | None = None,
        comments: str | None = None,
    ) -> SessionFeedback:
        fb = SessionFeedback(
            session_id=session_id,
            respondent=respondent,
            rating=rating,
            helpful=helpful,
            comments=comments,
        )
        self.db.add(fb)
        await self.db.flush()
        return fb

    async def get_feedback(self, session_id: uuid.UUID) -> Sequence[SessionFeedback]:
        stmt = (
            select(SessionFeedback)
            .where(SessionFeedback.session_id == session_id)
            .order_by(SessionFeedback.created_at)
        )
        result = await self.db.execute(stmt)
        return result.scalars().all()
