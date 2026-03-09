"""Profile Synthesis Engine — orchestrates LLM-backed profile generation.

Takes evidence graphs, cross-modal correlations, and signal features,
synthesizes them into bounded student profiles via Gemini.

Three-step synthesis:
1. Counsellor view — full evidence-backed analysis
2. Student view — derived from counsellor view, simplified + safety-screened
3. School view — aggregate-safe summary from counsellor view

Each step is an independent LLM call with its own prompt and schema.
"""

from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from typing import Any

from counselai.ingest.artifact_store import ArtifactStore
from counselai.live.providers.base import (
    SynthesisProviderBase,
    SynthesisRequest as ProviderSynthesisRequest,
)
from counselai.profiles.prompt_builder import PromptBuilder
from counselai.profiles.schemas import (
    CounsellorProfileView,
    RedFlag,
    SchoolProfileView,
    SessionProfile,
    StudentProfileView,
    SynthesisRequest,
    SynthesisResponse,
)
from counselai.profiles.validators import ProfileValidator
from counselai.settings import settings

logger = logging.getLogger(__name__)

# Max retries per synthesis step if validation fails
_MAX_RETRIES = 2


class ProfileSynthesisEngine:
    """Orchestrates multi-step profile synthesis from evidence to bounded output.

    Usage:
        engine = ProfileSynthesisEngine(synthesis_provider)
        profile = await engine.synthesize(session_id, turns, features...)
    """

    def __init__(
        self,
        provider: SynthesisProviderBase,
        prompt_builder: PromptBuilder | None = None,
        validator: ProfileValidator | None = None,
        artifact_store: ArtifactStore | None = None,
    ) -> None:
        self._provider = provider
        self._prompts = prompt_builder or PromptBuilder()
        self._validator = validator or ProfileValidator()
        self._store = artifact_store or ArtifactStore()

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    async def synthesize(
        self,
        session_id: uuid.UUID,
        turns: list[dict],
        content_features: dict | None = None,
        audio_features: dict | None = None,
        video_features: dict | None = None,
        evidence_graph: dict | None = None,
        topic_windows: list[dict] | None = None,
        student_context: str | None = None,
    ) -> SynthesisResponse:
        """Run the full synthesis pipeline.

        Args:
            session_id: Session UUID.
            turns: List of turn dicts (from turns.jsonl).
            content_features: Serialized ContentFeatures dict.
            audio_features: Serialized AudioFeatures dict.
            video_features: Serialized VideoFeatures dict.
            evidence_graph: Serialized evidence graph dict.
            topic_windows: List of topic window dicts.
            student_context: Prior session context string (optional).

        Returns:
            SynthesisResponse with parsed_profile and validation status.
        """
        logger.info("Starting profile synthesis for session %s", session_id)

        response = SynthesisResponse(session_id=session_id)
        all_errors: list[str] = []

        # Step 1: Counsellor view
        counsellor_view, c_errors = await self._synthesize_counsellor_view(
            session_id, turns, content_features, audio_features,
            video_features, evidence_graph, topic_windows, student_context,
        )
        all_errors.extend(c_errors)

        if counsellor_view is None:
            counsellor_view = CounsellorProfileView(
                summary="Profile synthesis failed — insufficient evidence or LLM error."
            )
            all_errors.append("Counsellor view synthesis failed; using fallback")

        # Step 2: Student view (derived from counsellor view)
        counsellor_dict = counsellor_view.model_dump(mode="json")
        student_view, s_errors = await self._synthesize_student_view(
            session_id, counsellor_dict, turns,
        )
        all_errors.extend(s_errors)

        if student_view is None:
            student_view = StudentProfileView(
                summary="Your session has been recorded and will be reviewed by your counsellor.",
                encouragement="Thank you for sharing your thoughts!",
            )
            all_errors.append("Student view synthesis failed; using fallback")

        # Safety sanitize student view regardless
        student_view = self._validator.sanitize_student_view(student_view)

        # Step 3: School view (derived from counsellor view)
        school_view, sch_errors = await self._synthesize_school_view(
            session_id, counsellor_dict,
        )
        all_errors.extend(sch_errors)

        if school_view is None:
            school_view = SchoolProfileView(
                summary="Session completed. Review pending.",
                primary_topics=[
                    c.label for c in counsellor_view.constructs[:5]
                ],
            )
            all_errors.append("School view synthesis failed; using fallback")

        # Assemble full profile
        profile = SessionProfile(
            session_id=session_id,
            profile_version=settings.processing_version,
            student_view=student_view,
            counsellor_view=counsellor_view,
            school_view=school_view,
            red_flags=list(counsellor_view.red_flags),
        )

        # Cross-view consistency check
        warnings = self._validator.validate_full_profile(profile)
        if warnings:
            for w in warnings:
                logger.warning("Profile consistency warning: %s", w)

        response.parsed_profile = profile
        response.validation_errors = all_errors
        response.is_valid = len([
            e for e in all_errors if "failed" in e.lower()
        ]) == 0

        logger.info(
            "Profile synthesis complete for session %s: valid=%s, errors=%d, warnings=%d",
            session_id, response.is_valid, len(all_errors), len(warnings),
        )

        return response

    # ------------------------------------------------------------------
    # Synthesis + persist (convenience)
    # ------------------------------------------------------------------

    async def synthesize_and_persist(
        self,
        session_id: uuid.UUID,
        turns: list[dict],
        content_features: dict | None = None,
        audio_features: dict | None = None,
        video_features: dict | None = None,
        evidence_graph: dict | None = None,
        topic_windows: list[dict] | None = None,
        student_context: str | None = None,
    ) -> SynthesisResponse:
        """Run synthesis and write artifact JSON to disk.

        Returns the SynthesisResponse. DB persistence should be done
        by the caller (worker job) using ProfileRepository.
        """
        response = await self.synthesize(
            session_id, turns, content_features, audio_features,
            video_features, evidence_graph, topic_windows, student_context,
        )

        if response.parsed_profile:
            self._persist_artifact(session_id, response.parsed_profile)

        return response

    # ------------------------------------------------------------------
    # Per-view synthesis (private)
    # ------------------------------------------------------------------

    async def _synthesize_counsellor_view(
        self,
        session_id: uuid.UUID,
        turns: list[dict],
        content_features: dict | None,
        audio_features: dict | None,
        video_features: dict | None,
        evidence_graph: dict | None,
        topic_windows: list[dict] | None,
        student_context: str | None,
    ) -> tuple[CounsellorProfileView | None, list[str]]:
        """Synthesize the counsellor profile view with retry on validation failure."""
        errors: list[str] = []

        system_prompt, user_prompt = self._prompts.build_counsellor_prompt(
            session_id, turns, content_features, audio_features,
            video_features, evidence_graph, topic_windows, student_context,
        )

        for attempt in range(_MAX_RETRIES + 1):
            try:
                llm_response = await self._provider.generate(
                    ProviderSynthesisRequest(
                        system_prompt=system_prompt,
                        user_prompt=user_prompt,
                        temperature=settings.gemini_synthesis_temperature,
                        max_tokens=settings.gemini_synthesis_max_tokens,
                    )
                )
            except Exception as e:
                errors.append(f"Counsellor LLM call failed (attempt {attempt + 1}): {e}")
                logger.error("Counsellor synthesis LLM error: %s", e, exc_info=True)
                continue

            view, val_errors = self._validator.validate_counsellor_view(llm_response.text)

            if view is not None:
                # Non-blocking errors are warnings
                if val_errors:
                    for ve in val_errors:
                        logger.warning("Counsellor view validation warning: %s", ve)
                logger.info(
                    "Counsellor view synthesized: %d constructs, %d red flags (attempt %d)",
                    len(view.constructs), len(view.red_flags), attempt + 1,
                )
                return view, val_errors

            errors.extend(val_errors)
            logger.warning(
                "Counsellor view validation failed (attempt %d/%d): %s",
                attempt + 1, _MAX_RETRIES + 1, val_errors,
            )

            # Add validation feedback to prompt for retry
            if attempt < _MAX_RETRIES:
                user_prompt += (
                    f"\n\n[RETRY — Previous output had these errors: {val_errors}. "
                    f"Fix them and return valid JSON.]"
                )

        return None, errors

    async def _synthesize_student_view(
        self,
        session_id: uuid.UUID,
        counsellor_profile: dict,
        turns: list[dict],
    ) -> tuple[StudentProfileView | None, list[str]]:
        """Synthesize the student-facing view with safety validation."""
        errors: list[str] = []

        system_prompt, user_prompt = self._prompts.build_student_prompt(
            session_id, counsellor_profile, turns,
        )

        for attempt in range(_MAX_RETRIES + 1):
            try:
                llm_response = await self._provider.generate(
                    ProviderSynthesisRequest(
                        system_prompt=system_prompt,
                        user_prompt=user_prompt,
                        temperature=0.4,  # Slightly warmer for student-facing
                        max_tokens=2048,
                    )
                )
            except Exception as e:
                errors.append(f"Student LLM call failed (attempt {attempt + 1}): {e}")
                logger.error("Student synthesis LLM error: %s", e, exc_info=True)
                continue

            view, val_errors = self._validator.validate_student_view(llm_response.text)

            if view is not None and not any("clinical" in e.lower() for e in val_errors):
                if val_errors:
                    for ve in val_errors:
                        logger.warning("Student view validation warning: %s", ve)
                logger.info("Student view synthesized (attempt %d)", attempt + 1)
                return view, val_errors

            errors.extend(val_errors)
            logger.warning(
                "Student view validation failed (attempt %d/%d): %s",
                attempt + 1, _MAX_RETRIES + 1, val_errors,
            )

            if attempt < _MAX_RETRIES:
                user_prompt += (
                    f"\n\n[RETRY — Previous output had these errors: {val_errors}. "
                    f"Remove any clinical language. Return valid JSON.]"
                )

        return None, errors

    async def _synthesize_school_view(
        self,
        session_id: uuid.UUID,
        counsellor_profile: dict,
    ) -> tuple[SchoolProfileView | None, list[str]]:
        """Synthesize the school-level summary view."""
        errors: list[str] = []

        system_prompt, user_prompt = self._prompts.build_school_prompt(
            session_id, counsellor_profile,
        )

        for attempt in range(_MAX_RETRIES + 1):
            try:
                llm_response = await self._provider.generate(
                    ProviderSynthesisRequest(
                        system_prompt=system_prompt,
                        user_prompt=user_prompt,
                        temperature=0.1,  # More deterministic for school view
                        max_tokens=1024,
                    )
                )
            except Exception as e:
                errors.append(f"School LLM call failed (attempt {attempt + 1}): {e}")
                logger.error("School synthesis LLM error: %s", e, exc_info=True)
                continue

            view, val_errors = self._validator.validate_school_view(llm_response.text)

            if view is not None:
                if val_errors:
                    for ve in val_errors:
                        logger.warning("School view validation warning: %s", ve)
                logger.info("School view synthesized (attempt %d)", attempt + 1)
                return view, val_errors

            errors.extend(val_errors)
            logger.warning(
                "School view validation failed (attempt %d/%d): %s",
                attempt + 1, _MAX_RETRIES + 1, val_errors,
            )

            if attempt < _MAX_RETRIES:
                user_prompt += (
                    f"\n\n[RETRY — Previous output had errors: {val_errors}. "
                    f"Return valid JSON.]"
                )

        return None, errors

    # ------------------------------------------------------------------
    # Artifact persistence
    # ------------------------------------------------------------------

    def _persist_artifact(
        self, session_id: uuid.UUID, profile: SessionProfile
    ) -> Path:
        """Write profile JSON to the session's analysis directory."""
        session_dir = self._store.session_dir(str(session_id))
        analysis_dir = session_dir / "analysis"
        analysis_dir.mkdir(parents=True, exist_ok=True)

        profile_path = analysis_dir / "profile.json"
        profile_path.write_text(
            profile.model_dump_json(indent=2),
            encoding="utf-8",
        )

        logger.info("Profile artifact written: %s", profile_path)
        return profile_path


# ---------------------------------------------------------------------------
# Convenience: load evidence from artifacts and run synthesis
# ---------------------------------------------------------------------------

async def synthesize_session_profile(
    session_id: str,
    provider: SynthesisProviderBase | None = None,
    store: ArtifactStore | None = None,
) -> SynthesisResponse:
    """High-level helper: load all evidence artifacts and run synthesis.

    This is the function worker jobs should call.
    """
    from counselai.live.providers.gemini import GeminiSynthesisProvider

    store = store or ArtifactStore()
    provider = provider or GeminiSynthesisProvider()

    uid = uuid.UUID(session_id)

    # Load turns
    turns = store.read_jsonl(session_id, "turns.jsonl")

    # Load feature artifacts (graceful if missing)
    content_features = store.read_json(session_id, "features/content.json")
    audio_features = store.read_json(session_id, "features/audio.json")
    video_features = store.read_json(session_id, "features/video.json")

    # Load analysis artifacts from Task 9-10
    evidence_graph = store.read_json(session_id, "analysis/evidence-graph.json")
    topic_windows_raw = store.read_json(session_id, "features/topic_windows.json")
    topic_windows = topic_windows_raw if isinstance(topic_windows_raw, list) else None

    logger.info(
        "Loaded evidence for session %s: turns=%d, content=%s, audio=%s, "
        "video=%s, evidence_graph=%s, topic_windows=%s",
        session_id,
        len(turns) if turns else 0,
        "yes" if content_features else "no",
        "yes" if audio_features else "no",
        "yes" if video_features else "no",
        "yes" if evidence_graph else "no",
        f"{len(topic_windows)}" if topic_windows else "no",
    )

    engine = ProfileSynthesisEngine(provider, artifact_store=store)

    return await engine.synthesize_and_persist(
        session_id=uid,
        turns=turns or [],
        content_features=content_features,
        audio_features=audio_features,
        video_features=video_features,
        evidence_graph=evidence_graph,
        topic_windows=topic_windows,
    )
