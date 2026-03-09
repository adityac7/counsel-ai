"""Repository for profile and hypothesis access."""

from __future__ import annotations

import uuid
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from counselai.storage.models import (
    Hypothesis,
    HypothesisStatus,
    Profile,
    SignalObservation,
    SignalWindow,
)


class ProfileRepository:
    """Encapsulates profile, hypothesis, and signal queries."""

    def __init__(self, db: Session) -> None:
        self.db = db

    # -- Profiles -----------------------------------------------------------

    def create(
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
        self.db.flush()
        return profile

    def get_latest(self, session_id: uuid.UUID) -> Profile | None:
        stmt = (
            select(Profile)
            .where(Profile.session_id == session_id)
            .order_by(Profile.created_at.desc())
            .limit(1)
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def list_by_session(self, session_id: uuid.UUID) -> Sequence[Profile]:
        stmt = (
            select(Profile)
            .where(Profile.session_id == session_id)
            .order_by(Profile.created_at.desc())
        )
        return self.db.execute(stmt).scalars().all()

    # -- Hypotheses ---------------------------------------------------------

    def add_hypothesis(
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
            status=status,
            score=score,
            evidence_summary=evidence_summary,
            evidence_refs_json=evidence_refs_json or {},
        )
        self.db.add(hyp)
        self.db.flush()
        return hyp

    def get_hypotheses(self, session_id: uuid.UUID) -> Sequence[Hypothesis]:
        stmt = (
            select(Hypothesis)
            .where(Hypothesis.session_id == session_id)
            .order_by(Hypothesis.construct_key)
        )
        return self.db.execute(stmt).scalars().all()

    # -- Signal windows & observations --------------------------------------

    def add_signal_window(
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
            source_turn_ids=source_turn_ids or [],
            reliability_score=reliability_score,
        )
        self.db.add(window)
        self.db.flush()
        return window

    def add_observation(
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
        from counselai.storage.models import Modality as ModalityEnum

        obs = SignalObservation(
            session_id=session_id,
            window_id=window_id,
            modality=ModalityEnum(modality),
            signal_key=signal_key,
            value_json=value_json,
            confidence=confidence,
            evidence_ref_json=evidence_ref_json or {},
        )
        self.db.add(obs)
        self.db.flush()
        return obs

    def get_observations(
        self, session_id: uuid.UUID, *, modality: str | None = None
    ) -> Sequence[SignalObservation]:
        stmt = select(SignalObservation).where(
            SignalObservation.session_id == session_id
        )
        if modality is not None:
            from counselai.storage.models import Modality as ModalityEnum

            stmt = stmt.where(
                SignalObservation.modality == ModalityEnum(modality)
            )
        stmt = stmt.order_by(SignalObservation.signal_key)
        return self.db.execute(stmt).scalars().all()
