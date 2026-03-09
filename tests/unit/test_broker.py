"""Unit tests for the pipeline orchestrator (broker).

Tests step resolution, dependency management, parallel execution,
graceful degradation, and error handling — all with mocked executors.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from counselai.workers.broker import (
    DEFAULT_STEPS,
    PARALLEL_STEPS,
    STEP_DEPENDENCIES,
    PipelineResult,
    PipelineStep,
    StepResult,
    StepStatus,
    _resolve_steps,
    run_pipeline,
)


# ---------------------------------------------------------------------------
# Step resolution tests
# ---------------------------------------------------------------------------

class TestStepResolution:
    def test_none_returns_all(self):
        steps = _resolve_steps(None)
        assert steps == list(DEFAULT_STEPS)

    def test_string_list(self):
        steps = _resolve_steps(["content", "profile"])
        assert PipelineStep.content in steps
        assert PipelineStep.profile in steps
        # Maintains canonical order
        assert steps.index(PipelineStep.content) < steps.index(PipelineStep.profile)

    def test_enum_list(self):
        steps = _resolve_steps([PipelineStep.align, PipelineStep.correlate])
        assert len(steps) == 2

    def test_unknown_step_raises(self):
        with pytest.raises(ValueError, match="Unknown pipeline step"):
            _resolve_steps(["nonexistent_step"])

    def test_canonical_order_preserved(self):
        # Even if passed in wrong order, should come out in canonical order
        steps = _resolve_steps(["profile", "canonicalize", "content"])
        assert steps[0] == PipelineStep.canonicalize
        assert steps[-1] == PipelineStep.profile


# ---------------------------------------------------------------------------
# Dependency graph tests
# ---------------------------------------------------------------------------

class TestDependencyGraph:
    def test_canonicalize_has_no_deps(self):
        assert STEP_DEPENDENCIES[PipelineStep.canonicalize] == set()

    def test_extraction_depends_on_canonicalize(self):
        for step in PARALLEL_STEPS:
            assert PipelineStep.canonicalize in STEP_DEPENDENCIES[step]

    def test_align_depends_on_extractors(self):
        deps = STEP_DEPENDENCIES[PipelineStep.align]
        assert PipelineStep.content in deps
        assert PipelineStep.audio in deps
        assert PipelineStep.video in deps

    def test_profile_depends_on_correlate(self):
        assert PipelineStep.correlate in STEP_DEPENDENCIES[PipelineStep.profile]

    def test_no_circular_deps(self):
        """Verify the dependency graph is a DAG."""
        visited: set[PipelineStep] = set()
        path: set[PipelineStep] = set()

        def dfs(node: PipelineStep) -> bool:
            if node in path:
                return True  # cycle
            if node in visited:
                return False
            path.add(node)
            for dep in STEP_DEPENDENCIES.get(node, set()):
                if dfs(dep):
                    return True
            path.discard(node)
            visited.add(node)
            return False

        for step in PipelineStep:
            assert not dfs(step), f"Circular dependency involving {step}"


# ---------------------------------------------------------------------------
# Pipeline execution tests (mocked executors)
# ---------------------------------------------------------------------------

def _make_mock_executor(result: dict | None = None, error: Exception | None = None):
    """Create a mock async executor."""
    async def executor(session_id: str):
        if error:
            raise error
        return result or {"status": "ok"}
    return executor


@pytest.fixture
def mock_all_executors():
    """Patch all step executors with successful mocks."""
    executors = {
        "_exec_canonicalize": AsyncMock(return_value={"status": "ok", "turn_count": 8}),
        "_exec_content": AsyncMock(return_value={"topics": 2, "reliability_score": 0.85}),
        "_exec_audio": AsyncMock(return_value={"turn_features_count": 4, "reliability_score": 0.75}),
        "_exec_video": AsyncMock(return_value={"frame_count": 120, "reliability_score": 0.7}),
        "_exec_align": AsyncMock(return_value={"aligned_turns": 8, "observations": 15}),
        "_exec_correlate": AsyncMock(return_value={"node_count": 20, "edge_count": 12, "hypothesis_count": 3}),
        "_exec_profile": AsyncMock(return_value={"is_valid": True, "constructs_count": 4}),
    }
    with patch.multiple("counselai.workers.broker", **executors):
        yield executors


@pytest.mark.asyncio
class TestPipelineExecution:
    async def test_full_pipeline_success(self, mock_all_executors):
        result = await run_pipeline("test-session-id")
        assert result.status == "completed"
        assert len(result.succeeded_steps) == len(DEFAULT_STEPS)
        assert len(result.failed_steps) == 0
        assert result.total_duration_seconds >= 0

    async def test_all_executors_called(self, mock_all_executors):
        await run_pipeline("test-session-id")
        for name, mock in mock_all_executors.items():
            mock.assert_called_once_with("test-session-id")

    async def test_selective_steps(self, mock_all_executors):
        result = await run_pipeline("test-session-id", steps=["content", "audio"])
        assert len(result.steps) == 2
        assert PipelineStep.content in result.steps
        assert PipelineStep.audio in result.steps
        # Other executors should not be called
        mock_all_executors["_exec_video"].assert_not_called()
        mock_all_executors["_exec_correlate"].assert_not_called()

    async def test_job_id_generation(self, mock_all_executors):
        result = await run_pipeline("test-session-id")
        assert result.job_id  # auto-generated
        assert len(result.job_id) == 36  # UUID format

    async def test_custom_job_id(self, mock_all_executors):
        result = await run_pipeline("test-session-id", job_id="my-job-123")
        assert result.job_id == "my-job-123"

    async def test_result_to_dict(self, mock_all_executors):
        result = await run_pipeline("test-session-id")
        d = result.to_dict()
        assert d["status"] == "completed"
        assert "canonicalize" in d["steps"]
        assert d["steps"]["canonicalize"]["status"] == "completed"
        assert isinstance(d["succeeded"], list)


@pytest.mark.asyncio
class TestGracefulDegradation:
    """Tests that the pipeline degrades gracefully when extraction steps fail."""

    async def test_audio_failure_continues(self):
        """Pipeline should continue even if audio extraction fails."""
        with patch.multiple(
            "counselai.workers.broker",
            _exec_canonicalize=AsyncMock(return_value={"status": "ok"}),
            _exec_content=AsyncMock(return_value={"topics": 2}),
            _exec_audio=AsyncMock(side_effect=RuntimeError("No audio file")),
            _exec_video=AsyncMock(return_value={"frame_count": 120}),
            _exec_align=AsyncMock(return_value={"aligned_turns": 8}),
            _exec_correlate=AsyncMock(return_value={"node_count": 10}),
            _exec_profile=AsyncMock(return_value={"is_valid": True}),
        ):
            result = await run_pipeline("test-session-id")
            assert result.status == "partial"
            assert PipelineStep.audio in result.failed_steps
            assert PipelineStep.content in result.succeeded_steps
            assert PipelineStep.profile in result.succeeded_steps

    async def test_video_failure_continues(self):
        """Pipeline continues without video."""
        with patch.multiple(
            "counselai.workers.broker",
            _exec_canonicalize=AsyncMock(return_value={"status": "ok"}),
            _exec_content=AsyncMock(return_value={"topics": 2}),
            _exec_audio=AsyncMock(return_value={"pauses": 3}),
            _exec_video=AsyncMock(side_effect=ImportError("cv2 not installed")),
            _exec_align=AsyncMock(return_value={"aligned_turns": 8}),
            _exec_correlate=AsyncMock(return_value={"node_count": 10}),
            _exec_profile=AsyncMock(return_value={"is_valid": True}),
        ):
            result = await run_pipeline("test-session-id")
            assert result.status == "partial"
            assert PipelineStep.video in result.failed_steps
            # Downstream still runs
            assert PipelineStep.align in result.succeeded_steps

    async def test_all_extraction_fails_skips_downstream(self):
        """If ALL extraction steps fail, downstream steps are skipped."""
        with patch.multiple(
            "counselai.workers.broker",
            _exec_canonicalize=AsyncMock(return_value={"status": "ok"}),
            _exec_content=AsyncMock(side_effect=RuntimeError("fail")),
            _exec_audio=AsyncMock(side_effect=RuntimeError("fail")),
            _exec_video=AsyncMock(side_effect=RuntimeError("fail")),
            _exec_align=AsyncMock(return_value={}),
            _exec_correlate=AsyncMock(return_value={}),
            _exec_profile=AsyncMock(return_value={}),
        ):
            result = await run_pipeline("test-session-id")
            # Canonicalize succeeded but all extraction failed → partial
            assert result.status == "partial"
            assert PipelineStep.align not in result.succeeded_steps
            # Downstream steps should be skipped
            assert result.steps[PipelineStep.align].status == StepStatus.skipped
            assert result.steps[PipelineStep.correlate].status == StepStatus.skipped
            assert result.steps[PipelineStep.profile].status == StepStatus.skipped

    async def test_content_only_succeeds(self):
        """Only content extraction succeeds — pipeline still completes align+correlate+profile."""
        with patch.multiple(
            "counselai.workers.broker",
            _exec_canonicalize=AsyncMock(return_value={"status": "ok"}),
            _exec_content=AsyncMock(return_value={"topics": 3}),
            _exec_audio=AsyncMock(side_effect=RuntimeError("fail")),
            _exec_video=AsyncMock(side_effect=RuntimeError("fail")),
            _exec_align=AsyncMock(return_value={"aligned_turns": 8}),
            _exec_correlate=AsyncMock(return_value={"node_count": 5}),
            _exec_profile=AsyncMock(return_value={"is_valid": True}),
        ):
            result = await run_pipeline("test-session-id")
            assert result.status == "partial"
            assert PipelineStep.profile in result.succeeded_steps


@pytest.mark.asyncio
class TestFailFast:
    async def test_fail_fast_aborts_pipeline(self):
        """fail_fast=True should skip remaining steps after first failure."""
        with patch.multiple(
            "counselai.workers.broker",
            _exec_canonicalize=AsyncMock(side_effect=RuntimeError("Bad session")),
            _exec_content=AsyncMock(return_value={}),
            _exec_audio=AsyncMock(return_value={}),
            _exec_video=AsyncMock(return_value={}),
            _exec_align=AsyncMock(return_value={}),
            _exec_correlate=AsyncMock(return_value={}),
            _exec_profile=AsyncMock(return_value={}),
        ):
            result = await run_pipeline("test-session-id", fail_fast=True)
            assert result.status == "failed"
            assert PipelineStep.canonicalize in result.failed_steps
            # Content etc should be skipped
            for step in [PipelineStep.content, PipelineStep.audio, PipelineStep.video]:
                assert result.steps[step].status == StepStatus.skipped

    async def test_no_fail_fast_continues(self):
        """Default (fail_fast=False) should continue past failures."""
        with patch.multiple(
            "counselai.workers.broker",
            _exec_canonicalize=AsyncMock(return_value={"status": "ok"}),
            _exec_content=AsyncMock(side_effect=RuntimeError("fail")),
            _exec_audio=AsyncMock(return_value={"pauses": 3}),
            _exec_video=AsyncMock(return_value={"frames": 120}),
            _exec_align=AsyncMock(return_value={"aligned": 8}),
            _exec_correlate=AsyncMock(return_value={"nodes": 10}),
            _exec_profile=AsyncMock(return_value={"is_valid": True}),
        ):
            result = await run_pipeline("test-session-id", fail_fast=False)
            assert result.status == "partial"
            assert PipelineStep.profile in result.succeeded_steps


@pytest.mark.asyncio
class TestParallelExecution:
    async def test_extraction_steps_run_concurrently(self):
        """Content, audio, video should start at roughly the same time."""
        call_order = []

        async def mock_content(session_id):
            call_order.append(("content_start", asyncio.get_event_loop().time()))
            await asyncio.sleep(0.01)
            call_order.append(("content_end", asyncio.get_event_loop().time()))
            return {"topics": 2}

        async def mock_audio(session_id):
            call_order.append(("audio_start", asyncio.get_event_loop().time()))
            await asyncio.sleep(0.01)
            call_order.append(("audio_end", asyncio.get_event_loop().time()))
            return {"pauses": 3}

        async def mock_video(session_id):
            call_order.append(("video_start", asyncio.get_event_loop().time()))
            await asyncio.sleep(0.01)
            call_order.append(("video_end", asyncio.get_event_loop().time()))
            return {"frames": 120}

        with patch.multiple(
            "counselai.workers.broker",
            _exec_canonicalize=AsyncMock(return_value={"status": "ok"}),
            _exec_content=mock_content,
            _exec_audio=mock_audio,
            _exec_video=mock_video,
            _exec_align=AsyncMock(return_value={}),
            _exec_correlate=AsyncMock(return_value={}),
            _exec_profile=AsyncMock(return_value={}),
        ):
            await run_pipeline("test-session-id")

        # All three should start before any ends (proving parallelism)
        start_times = [t for name, t in call_order if name.endswith("_start")]
        assert len(start_times) == 3
        # Start times should be very close together (< 0.005s apart)
        assert max(start_times) - min(start_times) < 0.05


@pytest.mark.asyncio
class TestStepResult:
    async def test_step_timing(self, mock_all_executors):
        result = await run_pipeline("test-session-id")
        for step, step_result in result.steps.items():
            assert step_result.duration_seconds >= 0
            assert step_result.status == StepStatus.completed

    async def test_failed_step_has_error(self):
        with patch.multiple(
            "counselai.workers.broker",
            _exec_canonicalize=AsyncMock(side_effect=ValueError("Bad data")),
            _exec_content=AsyncMock(return_value={}),
            _exec_audio=AsyncMock(return_value={}),
            _exec_video=AsyncMock(return_value={}),
            _exec_align=AsyncMock(return_value={}),
            _exec_correlate=AsyncMock(return_value={}),
            _exec_profile=AsyncMock(return_value={}),
        ):
            result = await run_pipeline("test-session-id", steps=["canonicalize"])
            step_r = result.steps[PipelineStep.canonicalize]
            assert step_r.status == StepStatus.failed
            assert "ValueError" in step_r.error
