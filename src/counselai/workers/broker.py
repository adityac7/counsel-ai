"""Async job orchestrator — chains signal extraction → alignment → correlation → profile synthesis.

The broker manages the post-session processing pipeline:

    canonicalize → [content, audio, video] (parallel) → align → correlate → profile

Each step reads from and writes to the artifact store. The pipeline is
designed to degrade gracefully: if audio or video extraction fails, the
remaining modalities still proceed through alignment, correlation, and synthesis.

Usage:
    # Full pipeline
    result = await run_pipeline(session_id)

    # Selective steps
    result = await run_pipeline(session_id, steps=["content", "correlate", "profile"])

    # Sync wrapper for CLI / Dramatiq
    result = run_pipeline_sync(session_id)
"""

from __future__ import annotations

import asyncio
import enum
import logging
import time
import traceback
import uuid
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pipeline step definitions
# ---------------------------------------------------------------------------

class PipelineStep(str, enum.Enum):
    """Ordered processing steps in the post-session pipeline."""
    canonicalize = "canonicalize"
    content = "content"
    audio = "audio"
    video = "video"
    align = "align"
    correlate = "correlate"
    profile = "profile"


# Steps that can run in parallel (all signal extractors)
PARALLEL_STEPS = {PipelineStep.content, PipelineStep.audio, PipelineStep.video}

# Default full pipeline order
DEFAULT_STEPS: list[PipelineStep] = list(PipelineStep)

# Dependency graph: step → set of steps that must complete first
STEP_DEPENDENCIES: dict[PipelineStep, set[PipelineStep]] = {
    PipelineStep.canonicalize: set(),
    PipelineStep.content: {PipelineStep.canonicalize},
    PipelineStep.audio: {PipelineStep.canonicalize},
    PipelineStep.video: {PipelineStep.canonicalize},
    PipelineStep.align: {PipelineStep.content, PipelineStep.audio, PipelineStep.video},
    PipelineStep.correlate: {PipelineStep.align},
    PipelineStep.profile: {PipelineStep.correlate},
}


# ---------------------------------------------------------------------------
# Step result tracking
# ---------------------------------------------------------------------------

class StepStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"
    skipped = "skipped"


@dataclass
class StepResult:
    """Result of a single pipeline step execution."""
    step: PipelineStep
    status: StepStatus = StepStatus.pending
    result: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    duration_seconds: float = 0.0
    started_at: float | None = None
    completed_at: float | None = None


@dataclass
class PipelineResult:
    """Aggregated result of the full pipeline run."""
    session_id: str
    job_id: str
    steps: dict[PipelineStep, StepResult] = field(default_factory=dict)
    status: str = "pending"  # pending, running, completed, partial, failed
    started_at: float | None = None
    completed_at: float | None = None
    total_duration_seconds: float = 0.0

    @property
    def succeeded_steps(self) -> list[PipelineStep]:
        return [s for s, r in self.steps.items() if r.status == StepStatus.completed]

    @property
    def failed_steps(self) -> list[PipelineStep]:
        return [s for s, r in self.steps.items() if r.status == StepStatus.failed]

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "job_id": self.job_id,
            "status": self.status,
            "total_duration_seconds": self.total_duration_seconds,
            "steps": {
                step.value: {
                    "status": result.status.value,
                    "duration_seconds": result.duration_seconds,
                    "error": result.error,
                    "result_keys": list(result.result.keys()) if result.result else [],
                }
                for step, result in self.steps.items()
            },
            "succeeded": [s.value for s in self.succeeded_steps],
            "failed": [s.value for s in self.failed_steps],
        }


# ---------------------------------------------------------------------------
# Step executors — thin wrappers around jobs.py functions
# ---------------------------------------------------------------------------

async def _exec_canonicalize(session_id: str) -> dict:
    """Canonicalize step is a no-op if artifacts already exist (handled by ingest)."""
    from counselai.ingest.artifact_store import ArtifactStore

    store = ArtifactStore()
    turns_path = store.session_dir(session_id) / "turns.jsonl"
    if not turns_path.exists():
        return {"status": "no_turns", "warning": "turns.jsonl not found — session may not be ingested"}
    lines = turns_path.read_text().strip().splitlines()
    return {"status": "ok", "turn_count": len(lines)}


async def _exec_content(session_id: str) -> dict:
    """Run content signal extraction."""
    from counselai.workers.jobs import run_content_extraction
    return await asyncio.get_event_loop().run_in_executor(
        None, run_content_extraction, session_id,
    )


async def _exec_audio(session_id: str) -> dict:
    """Run audio signal extraction."""
    from counselai.workers.jobs import run_audio_extraction
    return await asyncio.get_event_loop().run_in_executor(
        None, run_audio_extraction, session_id,
    )


async def _exec_video(session_id: str) -> dict:
    """Run video signal extraction."""
    from counselai.workers.jobs import run_video_extraction
    return await asyncio.get_event_loop().run_in_executor(
        None, run_video_extraction, session_id,
    )


async def _exec_align(session_id: str) -> dict:
    """Run timeline alignment, normalization, and reliability scoring."""
    from counselai.workers.jobs import run_timeline_alignment
    return await asyncio.get_event_loop().run_in_executor(
        None, run_timeline_alignment, session_id,
    )


async def _exec_correlate(session_id: str) -> dict:
    """Run evidence graph construction and cross-modal correlation."""
    from counselai.workers.jobs import run_evidence_correlation
    return await asyncio.get_event_loop().run_in_executor(
        None, run_evidence_correlation, session_id,
    )


async def _exec_profile(session_id: str) -> dict:
    """Run profile synthesis."""
    from counselai.workers.jobs import run_profile_synthesis
    return await asyncio.get_event_loop().run_in_executor(
        None, run_profile_synthesis, session_id,
    )


# Step → executor name mapping (looked up dynamically for testability)
_STEP_EXECUTOR_NAMES: dict[PipelineStep, str] = {
    PipelineStep.canonicalize: "_exec_canonicalize",
    PipelineStep.content: "_exec_content",
    PipelineStep.audio: "_exec_audio",
    PipelineStep.video: "_exec_video",
    PipelineStep.align: "_exec_align",
    PipelineStep.correlate: "_exec_correlate",
    PipelineStep.profile: "_exec_profile",
}


def _get_executor(step: PipelineStep) -> Any:
    """Look up executor by name from the current module (supports patching)."""
    import counselai.workers.broker as _self
    return getattr(_self, _STEP_EXECUTOR_NAMES[step])


# ---------------------------------------------------------------------------
# Pipeline orchestrator
# ---------------------------------------------------------------------------

async def _run_step(
    session_id: str,
    step: PipelineStep,
    result: StepResult,
    *,
    allow_failure: bool = False,
) -> StepResult:
    """Execute a single pipeline step with timing and error handling."""
    result.status = StepStatus.running
    result.started_at = time.monotonic()

    executor = _get_executor(step)
    try:
        step_output = await executor(session_id)
        result.status = StepStatus.completed
        result.result = step_output if isinstance(step_output, dict) else {}

        # Check if the step returned an error key (soft failure)
        if isinstance(step_output, dict) and "error" in step_output:
            if allow_failure:
                result.status = StepStatus.failed
                result.error = step_output["error"]
            else:
                result.status = StepStatus.failed
                result.error = step_output["error"]

    except Exception as e:
        result.status = StepStatus.failed
        result.error = f"{type(e).__name__}: {e}"
        logger.error(
            "Pipeline step %s failed for session %s: %s",
            step.value, session_id, e,
        )
        logger.debug(traceback.format_exc())

    result.completed_at = time.monotonic()
    result.duration_seconds = round(
        (result.completed_at or 0) - (result.started_at or 0), 3
    )
    return result


def _resolve_steps(
    requested: list[PipelineStep] | list[str] | None,
) -> list[PipelineStep]:
    """Resolve and validate requested steps, maintaining correct order."""
    if requested is None:
        return list(DEFAULT_STEPS)

    steps = []
    for s in requested:
        if isinstance(s, str):
            try:
                steps.append(PipelineStep(s))
            except ValueError:
                raise ValueError(f"Unknown pipeline step: {s}")
        else:
            steps.append(s)

    # Maintain canonical order
    ordered = [s for s in DEFAULT_STEPS if s in steps]
    return ordered


async def run_pipeline(
    session_id: str,
    *,
    steps: list[PipelineStep] | list[str] | None = None,
    job_id: str | None = None,
    fail_fast: bool = False,
) -> PipelineResult:
    """Run the post-session processing pipeline.

    Args:
        session_id: UUID of the session to process.
        steps: Subset of steps to run (default: all).
        job_id: Tracking ID (auto-generated if not provided).
        fail_fast: If True, abort on first failure. If False (default),
                   extraction steps (content/audio/video) can fail independently
                   and the pipeline continues with whatever succeeded.

    Returns:
        PipelineResult with per-step status and timing.
    """
    resolved = _resolve_steps(steps)
    jid = job_id or str(uuid.uuid4())

    pipeline = PipelineResult(
        session_id=session_id,
        job_id=jid,
        steps={s: StepResult(step=s) for s in resolved},
        status="running",
        started_at=time.monotonic(),
    )

    logger.info(
        "Starting pipeline for session %s (job=%s, steps=%s)",
        session_id, jid, [s.value for s in resolved],
    )

    # Build phases from the dependency graph (topological layers).
    # Phase 1: canonicalize
    # Phase 2: content, audio, video (parallel)
    # Phase 3: align
    # Phase 4: correlate
    # Phase 5: profile

    phases: list[list[PipelineStep]] = []
    remaining = list(resolved)
    placed: set[PipelineStep] = set()
    # Steps not in our resolved set are assumed already done
    all_known = set(resolved)

    while remaining:
        ready = []
        for s in remaining:
            deps = STEP_DEPENDENCIES.get(s, set())
            # Only consider deps that are in our step list
            relevant_deps = deps & all_known
            if relevant_deps <= placed:
                ready.append(s)

        if not ready:
            # Shouldn't happen if deps are correct, but break to avoid infinite loop
            for s in remaining:
                pipeline.steps[s].status = StepStatus.skipped
                pipeline.steps[s].error = "Unresolvable dependencies"
            break

        phases.append(ready)
        for s in ready:
            remaining.remove(s)
            placed.add(s)

    # Execute phases
    for phase in phases:
        # Check if we should abort (fail_fast + prior failure)
        if fail_fast and pipeline.failed_steps:
            for s in phase:
                if s in pipeline.steps:
                    pipeline.steps[s].status = StepStatus.skipped
                    pipeline.steps[s].error = "Skipped due to prior failure (fail_fast=True)"
            continue

        # Signal extraction steps (content/audio/video) are allowed to fail
        # independently — the pipeline continues with whatever data is available
        parallel_in_phase = [s for s in phase if s in PARALLEL_STEPS]
        sequential_in_phase = [s for s in phase if s not in PARALLEL_STEPS]

        # Run parallel steps concurrently
        if parallel_in_phase:
            tasks = []
            for s in parallel_in_phase:
                tasks.append(
                    _run_step(session_id, s, pipeline.steps[s], allow_failure=True)
                )
            await asyncio.gather(*tasks)

            # Log parallel results
            for s in parallel_in_phase:
                r = pipeline.steps[s]
                logger.info(
                    "  %s: %s (%.1fs)",
                    s.value, r.status.value, r.duration_seconds,
                )

        # Run sequential steps one at a time
        for s in sequential_in_phase:
            # For downstream steps (align, correlate, profile), check if
            # at least one extraction step succeeded
            if s in (PipelineStep.align, PipelineStep.correlate, PipelineStep.profile):
                extraction_steps = PARALLEL_STEPS & set(resolved)
                extraction_results = {
                    es: pipeline.steps.get(es)
                    for es in extraction_steps
                    if es in pipeline.steps
                }
                all_failed = all(
                    r.status == StepStatus.failed
                    for r in extraction_results.values()
                ) if extraction_results else False

                if all_failed and extraction_results:
                    pipeline.steps[s].status = StepStatus.skipped
                    pipeline.steps[s].error = "All extraction steps failed"
                    logger.warning(
                        "Skipping %s — all extraction steps failed", s.value,
                    )
                    continue

            await _run_step(session_id, s, pipeline.steps[s])
            r = pipeline.steps[s]
            logger.info(
                "  %s: %s (%.1fs)", s.value, r.status.value, r.duration_seconds,
            )

            if fail_fast and r.status == StepStatus.failed:
                # Skip remaining steps in this phase
                break

    # Determine overall status
    pipeline.completed_at = time.monotonic()
    pipeline.total_duration_seconds = round(
        (pipeline.completed_at or 0) - (pipeline.started_at or 0), 3
    )

    if all(r.status == StepStatus.completed for r in pipeline.steps.values()):
        pipeline.status = "completed"
    elif all(r.status in (StepStatus.failed, StepStatus.skipped) for r in pipeline.steps.values()):
        pipeline.status = "failed"
    elif any(r.status == StepStatus.completed for r in pipeline.steps.values()):
        pipeline.status = "partial"
    else:
        pipeline.status = "failed"

    logger.info(
        "Pipeline %s for session %s: %s (%.1fs) — succeeded=%s, failed=%s",
        pipeline.status,
        session_id,
        jid,
        pipeline.total_duration_seconds,
        [s.value for s in pipeline.succeeded_steps],
        [s.value for s in pipeline.failed_steps],
    )

    return pipeline


def run_pipeline_sync(
    session_id: str,
    *,
    steps: list[str] | None = None,
    job_id: str | None = None,
    fail_fast: bool = False,
) -> PipelineResult:
    """Synchronous wrapper for run_pipeline.

    Use from CLI, Dramatiq workers, or any non-async context.
    """
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(
            run_pipeline(
                session_id,
                steps=steps,
                job_id=job_id,
                fail_fast=fail_fast,
            )
        )
    finally:
        loop.close()
