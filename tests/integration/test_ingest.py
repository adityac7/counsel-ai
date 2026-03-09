"""Integration tests for the session ingestion pipeline.

Tests the full canonicalizer flow: session creation, turn ingestion,
media storage, manifest generation, and status transitions.

Uses a temporary directory for artifact storage (no DB required).
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from counselai.ingest.artifact_store import ArtifactStore
from counselai.ingest.canonicalizer import RawTurn, SessionCanonicalizer
from counselai.ingest.manifest import ManifestBuilder, ManifestEntry, SessionManifest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_store(tmp_path: Path) -> ArtifactStore:
    return ArtifactStore(root=tmp_path / "artifacts")


@pytest.fixture
def sample_turns() -> list[RawTurn]:
    return [
        RawTurn(
            turn_index=0,
            speaker="counsellor",
            start_ms=0,
            end_ms=5000,
            text="Namaste beta, kaise ho?",
            source="live_transcript",
            confidence=0.95,
        ),
        RawTurn(
            turn_index=1,
            speaker="student",
            start_ms=5500,
            end_ms=12000,
            text="Main theek hoon sir, bas thoda confused hoon career ke baare mein.",
            source="live_transcript",
            confidence=0.88,
        ),
        RawTurn(
            turn_index=2,
            speaker="counsellor",
            start_ms=12500,
            end_ms=16000,
            text="Accha, kya confuse kar raha hai tumhe?",
            source="live_transcript",
            confidence=0.92,
        ),
    ]


# ---------------------------------------------------------------------------
# ArtifactStore tests
# ---------------------------------------------------------------------------

class TestArtifactStore:
    def test_session_dir_creation(self, tmp_store: ArtifactStore):
        sid = str(uuid.uuid4())
        d = tmp_store.session_dir(sid)
        assert d.exists()
        assert d.is_dir()

    def test_write_and_read_json(self, tmp_store: ArtifactStore):
        sid = str(uuid.uuid4())
        payload = {"key": "value", "nested": {"a": 1}}
        path, sha = tmp_store.write_json(sid, "test.json", payload)
        assert path.exists()
        assert len(sha) == 64  # SHA-256 hex

        loaded = tmp_store.read_json(sid, "test.json")
        assert loaded == payload

    def test_write_and_read_bytes(self, tmp_store: ArtifactStore):
        sid = str(uuid.uuid4())
        data = b"hello world audio bytes"
        path, sha = tmp_store.write_bytes(sid, "audio.raw.webm", data)
        assert path.exists()
        assert path.read_bytes() == data

    def test_write_and_read_jsonl(self, tmp_store: ArtifactStore):
        sid = str(uuid.uuid4())
        records = [
            {"turn_index": 0, "speaker": "student", "text": "Hello"},
            {"turn_index": 1, "speaker": "counsellor", "text": "Hi"},
        ]
        path, sha = tmp_store.write_jsonl(sid, "turns.jsonl", records)
        assert path.exists()

        loaded = tmp_store.read_jsonl(sid, "turns.jsonl")
        assert len(loaded) == 2
        assert loaded[0]["speaker"] == "student"
        assert loaded[1]["text"] == "Hi"

    def test_append_jsonl(self, tmp_store: ArtifactStore):
        sid = str(uuid.uuid4())
        tmp_store.append_jsonl(sid, "log.jsonl", {"event": "a"})
        tmp_store.append_jsonl(sid, "log.jsonl", {"event": "b"})
        records = tmp_store.read_jsonl(sid, "log.jsonl")
        assert len(records) == 2

    def test_exists_and_uri(self, tmp_store: ArtifactStore):
        sid = str(uuid.uuid4())
        assert not tmp_store.exists(sid, "nope.json")
        tmp_store.write_json(sid, "yes.json", {})
        assert tmp_store.exists(sid, "yes.json")
        assert tmp_store.uri(sid, "yes.json") == f"sessions/{sid}/yes.json"

    def test_features_and_analysis_dirs(self, tmp_store: ArtifactStore):
        sid = str(uuid.uuid4())
        f = tmp_store.features_dir(sid)
        a = tmp_store.analysis_dir(sid)
        assert f.exists() and f.name == "features"
        assert a.exists() and a.name == "analysis"

    def test_compute_sha256(self, tmp_store: ArtifactStore):
        sid = str(uuid.uuid4())
        data = b"deterministic content"
        _, expected_sha = tmp_store.write_bytes(sid, "file.bin", data)
        computed = tmp_store.compute_sha256(sid, "file.bin")
        assert computed == expected_sha

    def test_read_nonexistent_json_returns_none(self, tmp_store: ArtifactStore):
        assert tmp_store.read_json("nonexistent", "nope.json") is None

    def test_read_nonexistent_jsonl_returns_empty(self, tmp_store: ArtifactStore):
        assert tmp_store.read_jsonl("nonexistent", "nope.jsonl") == []


# ---------------------------------------------------------------------------
# ManifestBuilder tests
# ---------------------------------------------------------------------------

class TestManifestBuilder:
    def test_build_minimal(self, tmp_store: ArtifactStore):
        sid = str(uuid.uuid4())
        builder = ManifestBuilder(tmp_store, sid)
        builder.set_session_meta(
            student_id=str(uuid.uuid4()),
            case_study_id="peer-pressure-01",
            provider="gemini-live",
        )
        manifest = builder.build(turn_count=3, status="uploaded")
        assert manifest.session_id == sid
        assert manifest.case_study_id == "peer-pressure-01"
        assert manifest.turn_count == 3
        assert manifest.status == "uploaded"
        assert manifest.artifacts == []

    def test_add_artifacts(self, tmp_store: ArtifactStore):
        sid = str(uuid.uuid4())
        builder = ManifestBuilder(tmp_store, sid)
        builder.set_session_meta(
            student_id="s1", case_study_id="c1", provider="gemini-live",
        )
        builder.add_artifact(
            artifact_type="audio_raw",
            storage_uri=f"sessions/{sid}/audio.raw.webm",
            sha256="abc123",
            metadata={"size_bytes": 1024},
        )
        manifest = builder.build()
        assert len(manifest.artifacts) == 1
        assert manifest.artifacts[0].artifact_type == "audio_raw"

    def test_save_writes_session_json(self, tmp_store: ArtifactStore):
        sid = str(uuid.uuid4())
        builder = ManifestBuilder(tmp_store, sid)
        builder.set_session_meta(
            student_id="s1", case_study_id="c1", provider="gemini-live",
        )
        uri = builder.save()
        assert uri == f"sessions/{sid}/session.json"

        loaded = tmp_store.read_json(sid, "session.json")
        assert loaded is not None
        assert loaded["session_id"] == sid


# ---------------------------------------------------------------------------
# SessionCanonicalizer tests (mocked DB)
# ---------------------------------------------------------------------------

class TestSessionCanonicalizer:
    """Tests the canonicalizer with a mocked DB session."""

    def _make_mock_session_record(self, session_id: uuid.UUID, student_id: uuid.UUID):
        """Create a mock SessionRecord."""
        from datetime import datetime, timezone
        rec = MagicMock()
        rec.id = session_id
        rec.student_id = student_id
        rec.case_study_id = "peer-pressure-01"
        rec.provider = "gemini-live"
        rec.status = MagicMock(value="draft")
        rec.started_at = datetime(2025, 3, 1, 10, 0, 0, tzinfo=timezone.utc)
        rec.ended_at = None
        rec.duration_seconds = None
        rec.primary_language = None
        rec.processing_version = "v1"
        rec.artifact_manifest_path = None
        return rec

    def test_ingest_turns_writes_jsonl(self, tmp_store: ArtifactStore, sample_turns: list[RawTurn]):
        sid = uuid.uuid4()
        db = MagicMock()
        canon = SessionCanonicalizer(db, store=tmp_store)

        # Mock repo methods
        canon.repo.add_turn = MagicMock()
        canon.repo.add_artifact = MagicMock()

        count = canon.ingest_turns(sid, sample_turns)
        assert count == 3

        # Verify turns.jsonl was written
        records = tmp_store.read_jsonl(str(sid), "turns.jsonl")
        assert len(records) == 3
        assert records[0]["speaker"] == "counsellor"
        assert records[1]["text"].startswith("Main theek")

        # Verify DB calls
        assert canon.repo.add_turn.call_count == 3
        assert canon.repo.add_artifact.call_count == 1  # transcript_canonical

    def test_ingest_audio(self, tmp_store: ArtifactStore):
        sid = uuid.uuid4()
        db = MagicMock()
        canon = SessionCanonicalizer(db, store=tmp_store)
        canon.repo.add_artifact = MagicMock()

        audio = b"\x00\x01\x02" * 100
        uri = canon.ingest_audio(sid, audio)

        assert uri is not None
        assert "audio.raw.webm" in uri
        assert tmp_store.exists(str(sid), "audio.raw.webm")
        canon.repo.add_artifact.assert_called_once()

    def test_ingest_video(self, tmp_store: ArtifactStore):
        sid = uuid.uuid4()
        db = MagicMock()
        canon = SessionCanonicalizer(db, store=tmp_store)
        canon.repo.add_artifact = MagicMock()

        video = b"\xff\xd8" * 500
        uri = canon.ingest_video(sid, video)

        assert uri is not None
        assert "video.raw.webm" in uri

    def test_finalize_session_full(self, tmp_store: ArtifactStore, sample_turns: list[RawTurn]):
        sid = uuid.uuid4()
        student_id = uuid.uuid4()
        db = MagicMock()
        canon = SessionCanonicalizer(db, store=tmp_store)

        mock_rec = self._make_mock_session_record(sid, student_id)
        canon.repo.get = MagicMock(return_value=mock_rec)
        canon.repo.add_turn = MagicMock()
        canon.repo.add_artifact = MagicMock()
        canon.repo.get_artifacts = MagicMock(return_value=[])

        audio = b"fake audio data"
        video = b"fake video data"

        result = canon.finalize_session(
            sid,
            raw_turns=sample_turns,
            audio_bytes=audio,
            video_bytes=video,
        )

        assert result is not None
        # Verify session.json manifest was written
        manifest = tmp_store.read_json(str(sid), "session.json")
        assert manifest is not None
        assert manifest["session_id"] == str(sid)
        assert manifest["status"] == "uploaded"
        assert manifest["turn_count"] == 3

        # Verify turns.jsonl exists
        turns = tmp_store.read_jsonl(str(sid), "turns.jsonl")
        assert len(turns) == 3

        # Verify media files exist
        assert tmp_store.exists(str(sid), "audio.raw.webm")
        assert tmp_store.exists(str(sid), "video.raw.webm")

        # Verify DB was committed
        db.commit.assert_called()

    def test_finalize_session_not_found(self, tmp_store: ArtifactStore):
        db = MagicMock()
        canon = SessionCanonicalizer(db, store=tmp_store)
        canon.repo.get = MagicMock(return_value=None)

        result = canon.finalize_session(uuid.uuid4())
        assert result is None

    def test_finalize_partial_on_media_failure(self, tmp_store: ArtifactStore, sample_turns: list[RawTurn]):
        """Browser failures should still leave a recoverable partial session."""
        sid = uuid.uuid4()
        student_id = uuid.uuid4()
        db = MagicMock()
        canon = SessionCanonicalizer(db, store=tmp_store)

        mock_rec = self._make_mock_session_record(sid, student_id)
        canon.repo.get = MagicMock(return_value=mock_rec)
        canon.repo.add_turn = MagicMock()
        canon.repo.add_artifact = MagicMock()
        canon.repo.get_artifacts = MagicMock(return_value=[])

        # Simulate audio write failure by patching store
        original_write = tmp_store.write_bytes
        def failing_write(s, filename, data):
            if "audio" in filename:
                raise IOError("Disk full")
            return original_write(s, filename, data)

        tmp_store.write_bytes = failing_write

        result = canon.finalize_session(
            sid,
            raw_turns=sample_turns,
            audio_bytes=b"will fail",
            video_bytes=None,
        )

        # Session should still be finalized despite audio failure
        assert result is not None
        # Turns should still be written
        turns = tmp_store.read_jsonl(str(sid), "turns.jsonl")
        assert len(turns) == 3
        db.commit.assert_called()

    def test_mark_processing(self, tmp_store: ArtifactStore):
        db = MagicMock()
        canon = SessionCanonicalizer(db, store=tmp_store)
        mock_session = MagicMock()
        canon.repo.update_status = MagicMock(return_value=mock_session)

        result = canon.mark_processing(uuid.uuid4())
        assert result is mock_session
        db.commit.assert_called()

    def test_mark_failed(self, tmp_store: ArtifactStore):
        sid = uuid.uuid4()
        db = MagicMock()
        canon = SessionCanonicalizer(db, store=tmp_store)
        mock_session = MagicMock()
        canon.repo.update_status = MagicMock(return_value=mock_session)

        result = canon.mark_failed(sid, reason="Processing timeout")
        assert result is mock_session
        # Verify failure marker was written
        failure = tmp_store.read_json(str(sid), "_failure.json")
        assert failure is not None
        assert failure["reason"] == "Processing timeout"
