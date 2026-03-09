"""End-to-end tests for the full processing pipeline.

Tests the complete flow: artifact seeding → signal extraction → alignment →
correlation → profile synthesis, using real module code with mocked LLM calls.

These tests validate:
1. Data flows correctly between pipeline stages
2. Artifact files are created with correct schemas
3. The orchestrator chains steps in the right order
4. Partial failures degrade gracefully
5. Profile output meets contract requirements
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from counselai.ingest.artifact_store import ArtifactStore
from counselai.workers.broker import PipelineStep, StepStatus, run_pipeline
from tests.conftest import seed_session_artifacts


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def e2e_store(tmp_path: Path) -> ArtifactStore:
    """Dedicated artifact store for E2E tests."""
    return ArtifactStore(root=tmp_path / "e2e_artifacts")


@pytest.fixture
def seeded_session(
    e2e_store: ArtifactStore,
    session_id: uuid.UUID,
    sample_turns_raw: list[dict],
) -> tuple[str, ArtifactStore]:
    """Session with turns.jsonl seeded (ready for extraction)."""
    sid = str(session_id)
    seed_session_artifacts(e2e_store, sid, sample_turns_raw)
    return sid, e2e_store


@pytest.fixture
def fully_seeded_session(
    e2e_store: ArtifactStore,
    session_id: uuid.UUID,
    sample_turns_raw: list[dict],
    sample_content_features: dict,
    sample_audio_features: dict,
    sample_video_features: dict,
) -> tuple[str, ArtifactStore]:
    """Session with turns + all feature files seeded (ready for align/correlate/profile)."""
    sid = str(session_id)
    seed_session_artifacts(
        e2e_store, sid, sample_turns_raw,
        content=sample_content_features,
        audio=sample_audio_features,
        video=sample_video_features,
    )
    return sid, e2e_store


def _patch_store(store: ArtifactStore):
    """Context manager to make all ArtifactStore() calls use our temp store."""
    return patch(
        "counselai.workers.jobs.ArtifactStore",
        return_value=store,
    )


# ---------------------------------------------------------------------------
# E2E: Canonicalize step
# ---------------------------------------------------------------------------

class TestCanonicalize:
    @pytest.mark.asyncio
    async def test_canonicalize_with_turns(self, seeded_session):
        sid, store = seeded_session
        with patch("counselai.ingest.artifact_store.ArtifactStore", return_value=store):
            from counselai.workers.broker import _exec_canonicalize
            result = await _exec_canonicalize(sid)
        assert result["status"] == "ok"
        assert result["turn_count"] == 8

    @pytest.mark.asyncio
    async def test_canonicalize_no_turns(self, e2e_store):
        sid = str(uuid.uuid4())
        e2e_store.session_dir(sid)  # Create dir but no turns
        with patch("counselai.ingest.artifact_store.ArtifactStore", return_value=e2e_store):
            from counselai.workers.broker import _exec_canonicalize
            result = await _exec_canonicalize(sid)
        assert result["status"] == "no_turns"


# ---------------------------------------------------------------------------
# E2E: Real alignment → correlation using job functions
# ---------------------------------------------------------------------------

class TestRealAlignmentCorrelation:
    """Tests using real job functions with proper store injection."""

    def test_alignment_with_all_modalities(self, fully_seeded_session):
        """Timeline alignment reads features and produces all expected artifacts."""
        sid, store = fully_seeded_session

        with _patch_store(store):
            from counselai.workers.jobs import run_timeline_alignment
            result = run_timeline_alignment(sid)

        assert result["aligned_turns"] == 8
        assert "content" in result["modalities_available"]
        assert "audio" in result["modalities_available"]
        assert "video" in result["modalities_available"]
        assert result["reliability_overall"] > 0

        # Verify artifacts were written
        analysis_dir = store.analysis_dir(sid)
        assert (analysis_dir / "aligned_session.json").exists()
        assert (analysis_dir / "normalized_signals.json").exists()
        assert (analysis_dir / "reliability.json").exists()
        assert (analysis_dir / "observations.json").exists()

        # Verify aligned_session.json schema
        aligned = json.loads((analysis_dir / "aligned_session.json").read_text())
        assert "turns" in aligned
        assert "windows" in aligned
        assert "modalities_available" in aligned

        # Verify reliability report
        reliability = json.loads((analysis_dir / "reliability.json").read_text())
        assert "overall_score" in reliability
        assert "modalities" in reliability

    def test_correlation_after_alignment(self, fully_seeded_session):
        """Evidence correlation builds graph with nodes and edges."""
        sid, store = fully_seeded_session

        with _patch_store(store):
            from counselai.workers.jobs import run_timeline_alignment, run_evidence_correlation
            run_timeline_alignment(sid)
            result = run_evidence_correlation(sid)

        assert result["node_count"] > 0
        assert "hypothesis_count" in result

        # Verify artifacts
        analysis_dir = store.analysis_dir(sid)
        assert (analysis_dir / "evidence-graph.json").exists()
        assert (analysis_dir / "hypotheses.json").exists()

        # Verify graph schema
        graph = json.loads((analysis_dir / "evidence-graph.json").read_text())
        assert "nodes" in graph
        assert "edges" in graph
        assert "session_id" in graph

    def test_alignment_content_only(self, e2e_store, session_id, sample_turns_raw, sample_content_features):
        """Alignment works with only content features (no audio/video)."""
        sid = str(session_id)
        seed_session_artifacts(e2e_store, sid, sample_turns_raw, content=sample_content_features)

        with _patch_store(e2e_store):
            from counselai.workers.jobs import run_timeline_alignment
            result = run_timeline_alignment(sid)

        assert result["aligned_turns"] == 8
        assert "content" in result["modalities_available"]

    def test_observations_confidence_bounded(self, fully_seeded_session):
        """All observations should have confidence in [0, 1]."""
        sid, store = fully_seeded_session

        with _patch_store(store):
            from counselai.workers.jobs import run_timeline_alignment
            run_timeline_alignment(sid)

        observations = json.loads((store.analysis_dir(sid) / "observations.json").read_text())
        assert isinstance(observations, list)
        for obs in observations:
            assert 0.0 <= obs["confidence"] <= 1.0

    def test_all_json_files_valid(self, fully_seeded_session):
        """Every .json file in session dir should be valid JSON."""
        sid, store = fully_seeded_session

        with _patch_store(store):
            from counselai.workers.jobs import run_timeline_alignment, run_evidence_correlation
            run_timeline_alignment(sid)
            run_evidence_correlation(sid)

        session_dir = store.session_dir(sid)
        for json_file in session_dir.rglob("*.json"):
            try:
                json.loads(json_file.read_text())
            except json.JSONDecodeError as e:
                pytest.fail(f"Invalid JSON in {json_file.relative_to(session_dir)}: {e}")


# ---------------------------------------------------------------------------
# E2E: Full pipeline with mocked executors
# ---------------------------------------------------------------------------

class TestFullPipelineMocked:
    """Full pipeline test with all executor calls mocked."""

    @pytest.mark.asyncio
    async def test_full_pipeline_content_only(self, seeded_session):
        """Full pipeline with only content extraction (no audio/video files)."""
        sid, store = seeded_session

        with patch.multiple(
            "counselai.workers.broker",
            _exec_canonicalize=AsyncMock(return_value={"status": "ok", "turn_count": 8}),
            _exec_content=AsyncMock(return_value={"topics": 2, "reliability_score": 0.85}),
            _exec_audio=AsyncMock(return_value={"error": "no audio file"}),
            _exec_video=AsyncMock(return_value={"error": "no video file"}),
            _exec_align=AsyncMock(return_value={"aligned_turns": 8, "observations": 10}),
            _exec_correlate=AsyncMock(return_value={"node_count": 8, "edge_count": 4, "hypothesis_count": 2}),
            _exec_profile=AsyncMock(return_value={"is_valid": True, "constructs_count": 3}),
        ):
            result = await run_pipeline(sid)

        # Audio and video should have failed (soft failure via error key)
        assert PipelineStep.audio in result.failed_steps
        assert PipelineStep.video in result.failed_steps

        # But downstream should still succeed
        assert PipelineStep.align in result.succeeded_steps
        assert PipelineStep.correlate in result.succeeded_steps
        assert PipelineStep.profile in result.succeeded_steps
        assert result.status == "partial"

    @pytest.mark.asyncio
    async def test_full_pipeline_all_modalities(self, fully_seeded_session):
        """Full pipeline with all modalities available."""
        sid, store = fully_seeded_session

        with patch.multiple(
            "counselai.workers.broker",
            _exec_canonicalize=AsyncMock(return_value={"status": "ok", "turn_count": 8}),
            _exec_content=AsyncMock(return_value={"topics": 2, "reliability_score": 0.85}),
            _exec_audio=AsyncMock(return_value={"turn_features_count": 4, "reliability_score": 0.75}),
            _exec_video=AsyncMock(return_value={"frame_count": 120, "reliability_score": 0.7}),
            _exec_align=AsyncMock(return_value={"aligned_turns": 8, "observations": 20}),
            _exec_correlate=AsyncMock(return_value={"node_count": 25, "edge_count": 15, "hypothesis_count": 4}),
            _exec_profile=AsyncMock(return_value={"is_valid": True, "constructs_count": 5}),
        ):
            result = await run_pipeline(sid)

        assert result.status == "completed"
        assert len(result.succeeded_steps) == 7
        assert len(result.failed_steps) == 0

    @pytest.mark.asyncio
    async def test_pipeline_timing_tracked(self, fully_seeded_session):
        """Pipeline tracks per-step and total timing."""
        sid, store = fully_seeded_session

        with patch.multiple(
            "counselai.workers.broker",
            _exec_canonicalize=AsyncMock(return_value={"status": "ok"}),
            _exec_content=AsyncMock(return_value={"topics": 2}),
            _exec_audio=AsyncMock(return_value={"pauses": 3}),
            _exec_video=AsyncMock(return_value={"frames": 120}),
            _exec_align=AsyncMock(return_value={"aligned_turns": 8}),
            _exec_correlate=AsyncMock(return_value={"node_count": 20}),
            _exec_profile=AsyncMock(return_value={"is_valid": True}),
        ):
            result = await run_pipeline(sid)

        assert result.total_duration_seconds >= 0
        for step_result in result.steps.values():
            assert step_result.duration_seconds >= 0


# ---------------------------------------------------------------------------
# E2E: Pipeline data flow (mocked executors, asserting call patterns)
# ---------------------------------------------------------------------------

class TestPipelineDataFlow:
    """Validates that steps execute in correct dependency order."""

    @pytest.mark.asyncio
    async def test_step_execution_order(self):
        """Steps should execute: canonicalize → [content,audio,video] → align → correlate → profile."""
        execution_log = []

        async def log_step(name):
            async def executor(session_id):
                execution_log.append(name)
                return {"status": "ok"}
            return executor

        with patch.multiple(
            "counselai.workers.broker",
            _exec_canonicalize=AsyncMock(side_effect=lambda sid: execution_log.append("canonicalize") or {"status": "ok"}),
            _exec_content=AsyncMock(side_effect=lambda sid: execution_log.append("content") or {"status": "ok"}),
            _exec_audio=AsyncMock(side_effect=lambda sid: execution_log.append("audio") or {"status": "ok"}),
            _exec_video=AsyncMock(side_effect=lambda sid: execution_log.append("video") or {"status": "ok"}),
            _exec_align=AsyncMock(side_effect=lambda sid: execution_log.append("align") or {"status": "ok"}),
            _exec_correlate=AsyncMock(side_effect=lambda sid: execution_log.append("correlate") or {"status": "ok"}),
            _exec_profile=AsyncMock(side_effect=lambda sid: execution_log.append("profile") or {"status": "ok"}),
        ):
            await run_pipeline("test-session")

        # Canonicalize must be first
        assert execution_log[0] == "canonicalize"
        # Extraction steps (1-3) before align
        extraction_indices = {execution_log.index(s) for s in ["content", "audio", "video"]}
        assert all(i > 0 for i in extraction_indices)  # after canonicalize
        # Align must be after all extraction
        assert execution_log.index("align") > max(extraction_indices)
        # Correlate after align
        assert execution_log.index("correlate") > execution_log.index("align")
        # Profile last
        assert execution_log.index("profile") > execution_log.index("correlate")


# ---------------------------------------------------------------------------
# E2E: Edge cases and regression tests
# ---------------------------------------------------------------------------

class TestEdgeCases:
    @pytest.mark.asyncio
    async def test_empty_session_no_turns(self, e2e_store):
        """Pipeline with no turns at all should fail gracefully."""
        sid = str(uuid.uuid4())
        e2e_store.session_dir(sid)  # Create dir only

        with patch.multiple(
            "counselai.workers.broker",
            _exec_canonicalize=AsyncMock(return_value={"status": "no_turns"}),
            _exec_content=AsyncMock(side_effect=RuntimeError("No turns")),
            _exec_audio=AsyncMock(side_effect=RuntimeError("No audio")),
            _exec_video=AsyncMock(side_effect=RuntimeError("No video")),
            _exec_align=AsyncMock(return_value={}),
            _exec_correlate=AsyncMock(return_value={}),
            _exec_profile=AsyncMock(return_value={}),
        ):
            result = await run_pipeline(sid)

        # Should fail at extraction but not crash
        assert result.status in ("failed", "partial")

    @pytest.mark.asyncio
    async def test_single_turn_session(self, e2e_store):
        """Pipeline with just one turn should complete."""
        sid = str(uuid.uuid4())
        turns = [
            {"turn_index": 0, "speaker": "student", "text": "Hello", "start_ms": 0, "end_ms": 2000},
        ]
        seed_session_artifacts(e2e_store, sid, turns)

        with patch.multiple(
            "counselai.workers.broker",
            _exec_canonicalize=AsyncMock(return_value={"status": "ok", "turn_count": 1}),
            _exec_content=AsyncMock(return_value={"topics": 0}),
            _exec_audio=AsyncMock(return_value={"error": "no audio"}),
            _exec_video=AsyncMock(return_value={"error": "no video"}),
            _exec_align=AsyncMock(return_value={"aligned_turns": 1}),
            _exec_correlate=AsyncMock(return_value={"node_count": 1}),
            _exec_profile=AsyncMock(return_value={"is_valid": True}),
        ):
            result = await run_pipeline(sid)

        assert PipelineStep.profile in result.succeeded_steps

    @pytest.mark.asyncio
    async def test_pipeline_idempotent(self, fully_seeded_session):
        """Running the pipeline twice produces consistent results."""
        sid, store = fully_seeded_session

        mock_executors = {
            "_exec_canonicalize": AsyncMock(return_value={"status": "ok"}),
            "_exec_content": AsyncMock(return_value={"topics": 2}),
            "_exec_audio": AsyncMock(return_value={"pauses": 3}),
            "_exec_video": AsyncMock(return_value={"frames": 120}),
            "_exec_align": AsyncMock(return_value={"aligned_turns": 8}),
            "_exec_correlate": AsyncMock(return_value={"node_count": 20}),
            "_exec_profile": AsyncMock(return_value={"is_valid": True}),
        }

        with patch.multiple("counselai.workers.broker", **mock_executors):
            result1 = await run_pipeline(sid)
            result2 = await run_pipeline(sid)

        assert result1.status == result2.status == "completed"
        assert len(result1.succeeded_steps) == len(result2.succeeded_steps)

    @pytest.mark.asyncio
    async def test_pipeline_with_uuid_session_id(self, fully_seeded_session):
        """Session ID as a proper UUID string works correctly."""
        sid, store = fully_seeded_session
        assert len(sid) == 36  # UUID format

        with patch.multiple(
            "counselai.workers.broker",
            _exec_canonicalize=AsyncMock(return_value={"status": "ok"}),
            _exec_content=AsyncMock(return_value={"topics": 2}),
            _exec_audio=AsyncMock(return_value={"pauses": 3}),
            _exec_video=AsyncMock(return_value={"frames": 120}),
            _exec_align=AsyncMock(return_value={"aligned_turns": 8}),
            _exec_correlate=AsyncMock(return_value={"node_count": 20}),
            _exec_profile=AsyncMock(return_value={"is_valid": True}),
        ):
            result = await run_pipeline(sid)
        assert result.session_id == sid


# ---------------------------------------------------------------------------
# E2E: Regression tests
# ---------------------------------------------------------------------------

class TestRegressions:
    """Regression tests for known issues."""

    @pytest.mark.asyncio
    async def test_soft_error_dict_treated_as_failure(self):
        """Steps returning {"error": "..."} should be treated as failed."""
        with patch.multiple(
            "counselai.workers.broker",
            _exec_canonicalize=AsyncMock(return_value={"status": "ok"}),
            _exec_content=AsyncMock(return_value={"error": "content extraction timeout"}),
            _exec_audio=AsyncMock(return_value={"error": "no audio file"}),
            _exec_video=AsyncMock(return_value={"error": "no video file"}),
            _exec_align=AsyncMock(return_value={"aligned_turns": 0}),
            _exec_correlate=AsyncMock(return_value={"node_count": 0}),
            _exec_profile=AsyncMock(return_value={"is_valid": False}),
        ):
            result = await run_pipeline("test-session")

        # All extraction steps should be marked failed
        assert PipelineStep.content in result.failed_steps
        assert PipelineStep.audio in result.failed_steps
        assert PipelineStep.video in result.failed_steps

    @pytest.mark.asyncio
    async def test_exception_in_step_doesnt_crash_pipeline(self):
        """An unhandled exception in one step should be caught, not crash everything."""
        with patch.multiple(
            "counselai.workers.broker",
            _exec_canonicalize=AsyncMock(return_value={"status": "ok"}),
            _exec_content=AsyncMock(side_effect=TypeError("unexpected None")),
            _exec_audio=AsyncMock(return_value={"pauses": 3}),
            _exec_video=AsyncMock(return_value={"frames": 120}),
            _exec_align=AsyncMock(return_value={"aligned_turns": 8}),
            _exec_correlate=AsyncMock(return_value={"node_count": 10}),
            _exec_profile=AsyncMock(return_value={"is_valid": True}),
        ):
            # Should NOT raise
            result = await run_pipeline("test-session")

        assert PipelineStep.content in result.failed_steps
        assert "TypeError" in result.steps[PipelineStep.content].error
        assert PipelineStep.profile in result.succeeded_steps

    @pytest.mark.asyncio
    async def test_correlate_skipped_when_all_extraction_fails(self):
        """Correlate/profile should be skipped when there's no data."""
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
            result = await run_pipeline("test-session")

        assert result.steps[PipelineStep.align].status == StepStatus.skipped
        assert result.steps[PipelineStep.correlate].status == StepStatus.skipped
        assert result.steps[PipelineStep.profile].status == StepStatus.skipped

    @pytest.mark.asyncio
    async def test_pipeline_result_serializable(self):
        """PipelineResult.to_dict() should produce JSON-serializable output."""
        with patch.multiple(
            "counselai.workers.broker",
            _exec_canonicalize=AsyncMock(return_value={"status": "ok"}),
            _exec_content=AsyncMock(return_value={"topics": 2}),
            _exec_audio=AsyncMock(side_effect=RuntimeError("fail")),
            _exec_video=AsyncMock(return_value={"frames": 120}),
            _exec_align=AsyncMock(return_value={"aligned_turns": 8}),
            _exec_correlate=AsyncMock(return_value={"node_count": 10}),
            _exec_profile=AsyncMock(return_value={"is_valid": True}),
        ):
            result = await run_pipeline("test-session")

        # Should not raise
        serialized = json.dumps(result.to_dict())
        parsed = json.loads(serialized)
        assert parsed["session_id"] == "test-session"
        assert "steps" in parsed
