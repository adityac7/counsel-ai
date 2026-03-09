"""Artifact manifest builder.

The manifest is a JSON file (session.json) that records every artifact
produced for a session, along with its type, storage URI, SHA-256 hash,
and metadata. It serves as the single source of truth for what exists
on disk and maps directly to `artifacts` rows in the database.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from counselai.ingest.artifact_store import ArtifactStore


# ---------------------------------------------------------------------------
# Manifest entry model
# ---------------------------------------------------------------------------

class ManifestEntry(BaseModel):
    """One artifact in the session manifest."""
    artifact_type: str
    storage_uri: str
    sha256: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class SessionManifest(BaseModel):
    """Top-level session manifest written to session.json."""
    session_id: str
    student_id: str
    case_study_id: str
    provider: str
    status: str = "draft"
    started_at: str = ""
    ended_at: str | None = None
    duration_seconds: int | None = None
    primary_language: str | None = None
    processing_version: str = "v1"
    artifacts: list[ManifestEntry] = Field(default_factory=list)
    turn_count: int = 0


# ---------------------------------------------------------------------------
# Manifest builder
# ---------------------------------------------------------------------------

class ManifestBuilder:
    """Incrementally builds a session manifest and persists it to disk."""

    def __init__(self, store: ArtifactStore, session_id: str) -> None:
        self.store = store
        self.session_id = session_id
        self._entries: list[ManifestEntry] = []
        self._meta: dict[str, Any] = {}

    def set_session_meta(
        self,
        *,
        student_id: str,
        case_study_id: str,
        provider: str,
        status: str = "draft",
        started_at: str = "",
        primary_language: str | None = None,
        processing_version: str = "v1",
    ) -> None:
        self._meta.update(
            student_id=student_id,
            case_study_id=case_study_id,
            provider=provider,
            status=status,
            started_at=started_at,
            primary_language=primary_language,
            processing_version=processing_version,
        )

    def add_artifact(
        self,
        *,
        artifact_type: str,
        storage_uri: str,
        sha256: str,
        metadata: dict[str, Any] | None = None,
    ) -> ManifestEntry:
        entry = ManifestEntry(
            artifact_type=artifact_type,
            storage_uri=storage_uri,
            sha256=sha256,
            metadata=metadata or {},
        )
        self._entries.append(entry)
        return entry

    def build(
        self,
        *,
        ended_at: str | None = None,
        duration_seconds: int | None = None,
        turn_count: int = 0,
        status: str | None = None,
    ) -> SessionManifest:
        """Build the final manifest object."""
        meta = dict(self._meta)
        if status:
            meta["status"] = status
        return SessionManifest(
            session_id=self.session_id,
            ended_at=ended_at,
            duration_seconds=duration_seconds,
            turn_count=turn_count,
            artifacts=list(self._entries),
            **meta,
        )

    def save(self, manifest: SessionManifest | None = None) -> str:
        """Write manifest to session.json and return the storage URI."""
        m = manifest or self.build()
        path, _ = self.store.write_json(
            self.session_id,
            "session.json",
            m.model_dump(),
        )
        return self.store.uri(self.session_id, "session.json")
