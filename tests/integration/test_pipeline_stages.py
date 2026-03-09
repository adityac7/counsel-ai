"""Integration tests for individual pipeline stages using real modules (mocked LLMs).

These tests use real CounselAI modules (not mocked executors) to validate
that actual data transformations work correctly end-to-end.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest

from counselai.ingest.artifact_store import ArtifactStore
from tests.conftest import seed_session_artifacts


def _patch_store(store: ArtifactStore):
    """Patch ArtifactStore constructor to return our temp store."""
    return patch(
        "counselai.workers.jobs.ArtifactStore",
        return_value=store,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def int_store(tmp_path: Path) -> ArtifactStore:
    return ArtifactStore(root=tmp_path / "int_artifacts")


@pytest.fixture
def full_session(
    int_store: ArtifactStore,
    session_id: uuid.UUID,
    sample_turns_raw: list[dict],
    sample_content_features: dict,
    sample_audio_features: dict,
    sample_video_features: dict,
) -> tuple[str, ArtifactStore]:
    """Session with all artifacts pre-seeded."""
    sid = str(session_id)
    seed_session_artifacts(
        int_store, sid, sample_turns_raw,
        content=sample_content_features,
        audio=sample_audio_features,
        video=sample_video_features,
    )
    return sid, int_store


# ---------------------------------------------------------------------------
# Timeline alignment integration
# ---------------------------------------------------------------------------

class TestTimelineAlignmentIntegration:
    def test_align_with_all_modalities(self, full_session):
        sid, store = full_session

        with _patch_store(store):
            from counselai.workers.jobs import run_timeline_alignment
            result = run_timeline_alignment(sid)

        assert result["aligned_turns"] == 8
        assert "content" in result["modalities_available"]
        assert "audio" in result["modalities_available"]
        assert "video" in result["modalities_available"]
        assert result["reliability_overall"] > 0

    def test_align_content_only(self, int_store, session_id, sample_turns_raw, sample_content_features):
        """Alignment works with only content features available."""
        sid = str(session_id)
        seed_session_artifacts(int_store, sid, sample_turns_raw, content=sample_content_features)

        with _patch_store(int_store):
            from counselai.workers.jobs import run_timeline_alignment
            result = run_timeline_alignment(sid)

        assert result["aligned_turns"] == 8
        assert "content" in result["modalities_available"]

    def test_aligned_session_schema(self, full_session):
        """Verify aligned_session.json has expected structure."""
        sid, store = full_session

        with _patch_store(store):
            from counselai.workers.jobs import run_timeline_alignment
            run_timeline_alignment(sid)

        data = json.loads((store.analysis_dir(sid) / "aligned_session.json").read_text())
        assert "session_id" in data
        assert "turns" in data
        assert "windows" in data
        assert "duration_ms" in data
        assert "modalities_available" in data

        # Each turn should have the expected fields
        if data["turns"]:
            turn = data["turns"][0]
            assert "turn_index" in turn
            assert "speaker" in turn

    def test_normalized_signals_schema(self, full_session):
        """Verify normalized_signals.json structure."""
        sid, store = full_session

        with _patch_store(store):
            from counselai.workers.jobs import run_timeline_alignment
            run_timeline_alignment(sid)

        data = json.loads((store.analysis_dir(sid) / "normalized_signals.json").read_text())
        assert isinstance(data, dict)

    def test_observations_confidence_bounded(self, full_session):
        """Observations should have confidence between 0 and 1."""
        sid, store = full_session

        with _patch_store(store):
            from counselai.workers.jobs import run_timeline_alignment
            run_timeline_alignment(sid)

        observations = json.loads((store.analysis_dir(sid) / "observations.json").read_text())
        assert isinstance(observations, list)
        for obs in observations:
            assert 0.0 <= obs["confidence"] <= 1.0


# ---------------------------------------------------------------------------
# Evidence correlation integration
# ---------------------------------------------------------------------------

class TestEvidenceCorrelationIntegration:
    def test_correlation_builds_graph(self, full_session):
        sid, store = full_session

        with _patch_store(store):
            from counselai.workers.jobs import run_timeline_alignment, run_evidence_correlation
            run_timeline_alignment(sid)
            result = run_evidence_correlation(sid)

        assert result["node_count"] > 0
        assert "hypothesis_count" in result

    def test_evidence_graph_schema(self, full_session):
        """Verify evidence graph JSON has required structure."""
        sid, store = full_session

        with _patch_store(store):
            from counselai.workers.jobs import run_timeline_alignment, run_evidence_correlation
            run_timeline_alignment(sid)
            run_evidence_correlation(sid)

        graph = json.loads((store.analysis_dir(sid) / "evidence-graph.json").read_text())
        assert "session_id" in graph
        assert "nodes" in graph
        assert "edges" in graph
        assert isinstance(graph["nodes"], list)
        assert isinstance(graph["edges"], list)

        # Each node should have required fields
        if graph["nodes"]:
            node = graph["nodes"][0]
            assert "id" in node
            assert "node_type" in node
            assert "session_id" in node

    def test_hypotheses_generated(self, full_session):
        """Verify hypotheses are generated from the evidence graph."""
        sid, store = full_session

        with _patch_store(store):
            from counselai.workers.jobs import run_timeline_alignment, run_evidence_correlation
            run_timeline_alignment(sid)
            result = run_evidence_correlation(sid)

        hypotheses = json.loads((store.analysis_dir(sid) / "hypotheses.json").read_text())
        assert isinstance(hypotheses, list)
        assert result["hypothesis_count"] == len(hypotheses)

        # Each hypothesis should have key fields
        for h in hypotheses:
            assert "construct_key" in h
            assert "status" in h
            assert "score" in h

    def test_cross_modal_observations_written(self, full_session):
        """Correlation should write cross_modal_observations.json."""
        sid, store = full_session

        with _patch_store(store):
            from counselai.workers.jobs import run_timeline_alignment, run_evidence_correlation
            run_timeline_alignment(sid)
            run_evidence_correlation(sid)

        analysis_dir = store.analysis_dir(sid)
        assert (analysis_dir / "cross_modal_observations.json").exists()
        obs = json.loads((analysis_dir / "cross_modal_observations.json").read_text())
        assert isinstance(obs, list)


# ---------------------------------------------------------------------------
# Artifact store integration
# ---------------------------------------------------------------------------

class TestArtifactIntegrity:
    """Verify artifact files are consistent across pipeline stages."""

    def test_features_dir_populated_after_seeding(self, full_session):
        sid, store = full_session
        features = store.features_dir(sid)
        assert (features / "content.json").exists()
        assert (features / "audio.json").exists()
        assert (features / "video.json").exists()

    def test_analysis_dir_populated_after_alignment(self, full_session):
        sid, store = full_session

        with _patch_store(store):
            from counselai.workers.jobs import run_timeline_alignment
            run_timeline_alignment(sid)

        analysis = store.analysis_dir(sid)
        expected_files = [
            "aligned_session.json",
            "normalized_signals.json",
            "reliability.json",
            "observations.json",
        ]
        for f in expected_files:
            assert (analysis / f).exists(), f"Missing: {f}"

    def test_analysis_dir_populated_after_correlation(self, full_session):
        sid, store = full_session

        with _patch_store(store):
            from counselai.workers.jobs import run_timeline_alignment, run_evidence_correlation
            run_timeline_alignment(sid)
            run_evidence_correlation(sid)

        analysis = store.analysis_dir(sid)
        assert (analysis / "evidence-graph.json").exists()
        assert (analysis / "hypotheses.json").exists()
        assert (analysis / "cross_modal_observations.json").exists()

    def test_all_json_files_parseable(self, full_session):
        """Every .json file in the session dir should be valid JSON."""
        sid, store = full_session

        with _patch_store(store):
            from counselai.workers.jobs import run_timeline_alignment, run_evidence_correlation
            run_timeline_alignment(sid)
            run_evidence_correlation(sid)

        session_dir = store.session_dir(sid)
        json_count = 0
        for json_file in session_dir.rglob("*.json"):
            json_count += 1
            try:
                json.loads(json_file.read_text())
            except json.JSONDecodeError as e:
                pytest.fail(f"Invalid JSON in {json_file.relative_to(session_dir)}: {e}")
        assert json_count >= 8  # At minimum: session + 3 features + 4 analysis files
