"""Async repositories for profiles, hypotheses, signals, and student profiles."""

from __future__ import annotations

import uuid
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from counselai.storage.models import (
    Hypothesis,
    HypothesisStatus,
    Modality,
    Profile,
    SignalObservation,
    SignalWindow,
    Student,
    StudentProfile,
)


class StudentProfileRepository:
    """CRUD for extended student profile (demographics, academic info)."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create(
        self,
        student_id: uuid.UUID,
        *,
        date_of_birth: str | None = None,
        gender: str | None = None,
        parent_contact: str | None = None,
        parent_name: str | None = None,
        address: str | None = None,
        academic_year: str | None = None,
        stream: str | None = None,
        gpa: float | None = None,
        attendance_pct: float | None = None,
        extracurriculars: dict | None = None,
        referral_reason: str | None = None,
        previous_counselling: bool = False,
        notes: str | None = None,
    ) -> StudentProfile:
        profile = StudentProfile(
            student_id=student_id,
            date_of_birth=date_of_birth,
            gender=gender,
            parent_contact=parent_contact,
            parent_name=parent_name,
            address=address,
            academic_year=academic_year,
            stream=stream,
            gpa=gpa,
            attendance_pct=attendance_pct,
            extracurriculars=extracurriculars,
            referral_reason=referral_reason,
            previous_counselling=previous_counselling,
            notes=notes,
        )
        self.db.add(profile)
        await self.db.flush()
        return profile

    async def get_by_student(self, student_id: uuid.UUID) -> StudentProfile | None:
        stmt = select(StudentProfile).where(StudentProfile.student_id == student_id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def update(
        self,
        student_id: uuid.UUID,
        **kwargs: object,
    ) -> StudentProfile | None:
        """Update profile fields. Pass only the fields to change."""
        profile = await self.get_by_student(student_id)
        if profile is None:
            return None
        allowed = {
            "date_of_birth", "gender", "parent_contact", "parent_name",
            "address", "academic_year", "stream", "gpa", "attendance_pct",
            "extracurriculars", "referral_reason", "previous_counselling", "notes",
        }
        for key, value in kwargs.items():
            if key in allowed:
                setattr(profile, key, value)
        await self.db.flush()
        return profile

    async def get_or_create(
        self, student_id: uuid.UUID, **kwargs: object
    ) -> tuple[StudentProfile, bool]:
        """Get existing profile or create new one. Returns (profile, created)."""
        existing = await self.get_by_student(student_id)
        if existing is not None:
            return existing, False
        profile = await self.create(student_id, **kwargs)  # type: ignore[arg-type]
        return profile, True

    async def list_all(
        self, *, offset: int = 0, limit: int = 50
    ) -> Sequence[StudentProfile]:
        stmt = (
            select(StudentProfile)
            .order_by(StudentProfile.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def search_students(
        self,
        *,
        name: str | None = None,
        grade: str | None = None,
        school_id: uuid.UUID | None = None,
    ) -> Sequence[Student]:
        """Search students by name/grade/school. Returns Student rows."""
        stmt = select(Student)
        if name is not None:
            stmt = stmt.where(Student.full_name.ilike(f"%{name}%"))
        if grade is not None:
            stmt = stmt.where(Student.grade == grade)
        if school_id is not None:
            stmt = stmt.where(Student.school_id == school_id)
        stmt = stmt.order_by(Student.full_name).limit(100)
        result = await self.db.execute(stmt)
        return result.scalars().all()


class ProfileRepository:
    """Async repository for session profiles, hypotheses, and signals."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # -- Session Profiles ---------------------------------------------------

    async def create(
        self,
        session_id: uuid.UUID,
        *,
        profile_version: str,
        student_view_json: dict | None = None,
        counsellor_view_json: dict | None = None,
        school_view_json: dict | None = None,
        red_flags_json: dict | None = None,
    ) -> Profile:
        profile = Profile(
            session_id=session_id,
            profile_version=profile_version,
            student_view_json=student_view_json or {},
            counsellor_view_json=counsellor_view_json or {},
            school_view_json=school_view_json or {},
            red_flags_json=red_flags_json or {},
        )
        self.db.add(profile)
        await self.db.flush()
        return profile

    async def get_latest(self, session_id: uuid.UUID) -> Profile | None:
        stmt = (
            select(Profile)
            .where(Profile.session_id == session_id)
            .order_by(Profile.created_at.desc())
            .limit(1)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_session(self, session_id: uuid.UUID) -> Sequence[Profile]:
        stmt = (
            select(Profile)
            .where(Profile.session_id == session_id)
            .order_by(Profile.created_at.desc())
        )
        result = await self.db.execute(stmt)
        return result.scalars().all()

    # -- Hypotheses ---------------------------------------------------------

    async def add_hypothesis(
        self,
        session_id: uuid.UUID,
        *,
        construct_key: str,
        label: str,
        status: HypothesisStatus,
        evidence_summary: str,
        score: float | None = None,
        evidence_refs_json: dict | None = None,
    ) -> Hypothesis:
        hyp = Hypothesis(
            session_id=session_id,
            construct_key=construct_key,
            label=label,
            status=status.value,
            score=score,
            evidence_summary=evidence_summary,
            evidence_refs_json=evidence_refs_json or {},
        )
        self.db.add(hyp)
        await self.db.flush()
        return hyp

    async def get_hypotheses(self, session_id: uuid.UUID) -> Sequence[Hypothesis]:
        stmt = (
            select(Hypothesis)
            .where(Hypothesis.session_id == session_id)
            .order_by(Hypothesis.construct_key)
        )
        result = await self.db.execute(stmt)
        return result.scalars().all()

    # -- Signal windows & observations --------------------------------------

    async def add_signal_window(
        self,
        session_id: uuid.UUID,
        *,
        topic_key: str,
        start_ms: int,
        end_ms: int,
        source_turn_ids: list[uuid.UUID] | None = None,
        reliability_score: float,
    ) -> SignalWindow:
        window = SignalWindow(
            session_id=session_id,
            topic_key=topic_key,
            start_ms=start_ms,
            end_ms=end_ms,
            source_turn_ids=[str(uid) for uid in (source_turn_ids or [])],
            reliability_score=reliability_score,
        )
        self.db.add(window)
        await self.db.flush()
        return window

    async def add_observation(
        self,
        session_id: uuid.UUID,
        *,
        window_id: uuid.UUID | None = None,
        modality: str,
        signal_key: str,
        value_json: dict,
        confidence: float,
        evidence_ref_json: dict | None = None,
    ) -> SignalObservation:
        obs = SignalObservation(
            session_id=session_id,
            window_id=window_id,
            modality=Modality(modality).value,
            signal_key=signal_key,
            value_json=value_json,
            confidence=confidence,
            evidence_ref_json=evidence_ref_json or {},
        )
        self.db.add(obs)
        await self.db.flush()
        return obs

    async def get_observations(
        self, session_id: uuid.UUID, *, modality: str | None = None
    ) -> Sequence[SignalObservation]:
        stmt = select(SignalObservation).where(
            SignalObservation.session_id == session_id
        )
        if modality is not None:
            stmt = stmt.where(
                SignalObservation.modality == Modality(modality).value
            )
        stmt = stmt.order_by(SignalObservation.signal_key)
        result = await self.db.execute(stmt)
        return result.scalars().all()
