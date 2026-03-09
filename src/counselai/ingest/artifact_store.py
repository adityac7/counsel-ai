"""Filesystem artifact storage with SHA-256 integrity tracking.

Manages the canonical artifact directory layout:
    artifacts/sessions/<session_id>/session.json
    artifacts/sessions/<session_id>/turns.jsonl
    artifacts/sessions/<session_id>/audio.raw.webm
    artifacts/sessions/<session_id>/video.raw.webm
    ...

Provides an abstraction layer so a future S3-compatible backend
can replace local filesystem without changing callers.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from counselai.settings import settings


class ArtifactStore:
    """Manages reading/writing session artifacts to the canonical directory layout."""

    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root or settings.artifact_root).resolve()

    # -- Path helpers -------------------------------------------------------

    def session_dir(self, session_id: str) -> Path:
        """Return (and create) the session artifact directory."""
        d = self.root / "sessions" / session_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def features_dir(self, session_id: str) -> Path:
        d = self.session_dir(session_id) / "features"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def analysis_dir(self, session_id: str) -> Path:
        d = self.session_dir(session_id) / "analysis"
        d.mkdir(parents=True, exist_ok=True)
        return d

    # -- Write helpers ------------------------------------------------------

    def write_bytes(self, session_id: str, filename: str, data: bytes) -> tuple[Path, str]:
        """Write raw bytes and return (path, sha256)."""
        path = self.session_dir(session_id) / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        sha = hashlib.sha256(data).hexdigest()
        path.write_bytes(data)
        return path, sha

    def write_json(self, session_id: str, filename: str, payload: dict | list) -> tuple[Path, str]:
        """Write JSON and return (path, sha256)."""
        data = json.dumps(payload, indent=2, default=str, ensure_ascii=False).encode("utf-8")
        return self.write_bytes(session_id, filename, data)

    def append_jsonl(self, session_id: str, filename: str, record: dict) -> Path:
        """Append a single JSON line to a JSONL file."""
        path = self.session_dir(session_id) / filename
        line = json.dumps(record, default=str, ensure_ascii=False) + "\n"
        with path.open("a", encoding="utf-8") as f:
            f.write(line)
        return path

    def write_jsonl(self, session_id: str, filename: str, records: list[dict]) -> tuple[Path, str]:
        """Write a complete JSONL file and return (path, sha256)."""
        lines = [json.dumps(r, default=str, ensure_ascii=False) for r in records]
        data = ("\n".join(lines) + "\n").encode("utf-8") if lines else b""
        return self.write_bytes(session_id, filename, data)

    # -- Read helpers -------------------------------------------------------

    def read_json(self, session_id: str, filename: str) -> dict | list | None:
        path = self.session_dir(session_id) / filename
        if not path.exists():
            return None
        return json.loads(path.read_text("utf-8"))

    def read_jsonl(self, session_id: str, filename: str) -> list[dict]:
        path = self.session_dir(session_id) / filename
        if not path.exists():
            return []
        records = []
        for line in path.read_text("utf-8").strip().splitlines():
            line = line.strip()
            if line:
                records.append(json.loads(line))
        return records

    def exists(self, session_id: str, filename: str) -> bool:
        return (self.session_dir(session_id) / filename).exists()

    def uri(self, session_id: str, filename: str) -> str:
        """Return a storage URI relative to the artifact root."""
        return f"sessions/{session_id}/{filename}"

    def compute_sha256(self, session_id: str, filename: str) -> str:
        """Compute SHA-256 of an existing artifact file."""
        path = self.session_dir(session_id) / filename
        return hashlib.sha256(path.read_bytes()).hexdigest()
