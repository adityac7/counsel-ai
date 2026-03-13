"""Legacy database compatibility wrapper.

This file preserves the old save_session / list_sessions / get_session
interface so existing code doesn't break during migration. Internally it
delegates to the new SQLAlchemy-based storage layer.

Once all callers are migrated to use repositories directly, this file
can be deleted.
"""

import json
import os
import sys
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# Ensure src/ is on the path for the new package
_SRC = os.path.join(os.path.dirname(__file__), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from counselai.storage.db import get_sync_session_factory, init_db  # noqa: E402
from counselai.storage.models import (  # noqa: E402
    SessionRecord,
    SessionStatus,
    Student,
)


class _NumpyEncoder(json.JSONEncoder):
    def default(self, obj: Any) -> Any:
        try:
            import numpy as np

            if isinstance(obj, (np.floating,)):
                return float(obj)
            if isinstance(obj, (np.integer,)):
                return int(obj)
            if isinstance(obj, np.ndarray):
                return obj.tolist()
        except ImportError:
            pass
        return super().default(obj)


def _get_session():
    """Get a sync DB session, initialising DB if needed."""
    init_db()
    factory = get_sync_session_factory()
    return factory()


def init_db_legacy() -> None:
    """No-op — tables are managed by Alembic migrations now."""
    pass


def save_session(
    *,
    source: str,
    external_session_id: Optional[str],
    student_info: Dict[str, Any],
    session_start_time: Optional[str],
    session_end_time: Optional[str],
    transcript: Any,
    face_analysis: Any,
    voice_analysis: Any,
    profile: Any,
) -> int:
    """Save a session using the new storage layer. Returns a numeric hash as ID."""
    db = _get_session()
    try:
        name = str(student_info.get("name", "Student"))
        grade = str(student_info.get("class", ""))
        section = str(student_info.get("section", ""))

        student = Student(
            full_name=name,
            grade=grade or "unknown",
            section=section or None,
            age=student_info.get("age"),
        )
        db.add(student)
        db.flush()

        started = None
        ended = None
        if session_start_time:
            try:
                started = datetime.fromisoformat(
                    session_start_time.replace("Z", "+00:00")
                )
            except ValueError:
                started = datetime.now(timezone.utc)
        if session_end_time:
            try:
                ended = datetime.fromisoformat(
                    session_end_time.replace("Z", "+00:00")
                )
            except ValueError:
                ended = datetime.now(timezone.utc)

        duration = None
        if started and ended:
            duration = max(int((ended - started).total_seconds()), 0)

        session = SessionRecord(
            student_id=student.id,
            case_study_id=source,
            provider=source,
            status=SessionStatus.completed.value,
            started_at=started or datetime.now(timezone.utc),
            ended_at=ended,
            duration_seconds=duration,
        )
        db.add(session)
        db.flush()
        db.commit()
        return session.id.int & 0x7FFFFFFF
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def list_sessions() -> List[Dict[str, Any]]:
    """List sessions in legacy format."""
    db = _get_session()
    try:
        sessions = (
            db.query(SessionRecord)
            .order_by(SessionRecord.started_at.desc())
            .limit(200)
            .all()
        )
        result = []
        for s in sessions:
            result.append(
                {
                    "id": s.id.int & 0x7FFFFFFF,
                    "source": s.provider,
                    "student_name": s.student.full_name if s.student else "",
                    "student_class": s.student.grade if s.student else "",
                    "student_section": s.student.section or "",
                    "school": "",
                    "age": s.student.age if s.student else None,
                    "session_start_time": (
                        s.started_at.isoformat() if s.started_at else None
                    ),
                    "session_end_time": (
                        s.ended_at.isoformat() if s.ended_at else None
                    ),
                    "duration_seconds": s.duration_seconds,
                    "created_at": (
                        s.started_at.isoformat() if s.started_at else None
                    ),
                }
            )
        return result
    finally:
        db.close()


def get_session(session_id: int) -> Optional[Dict[str, Any]]:
    """Get session by legacy int ID. Returns None if not found."""
    db = _get_session()
    try:
        sessions = db.query(SessionRecord).limit(500).all()
        for s in sessions:
            if (s.id.int & 0x7FFFFFFF) == session_id:
                return {
                    "id": session_id,
                    "source": s.provider,
                    "student_info": {
                        "name": s.student.full_name if s.student else "Student",
                        "class": s.student.grade if s.student else "",
                        "section": s.student.section or "",
                        "school": "",
                        "age": s.student.age if s.student else None,
                    },
                    "session_start_time": (
                        s.started_at.isoformat() if s.started_at else None
                    ),
                    "session_end_time": (
                        s.ended_at.isoformat() if s.ended_at else None
                    ),
                    "duration_seconds": s.duration_seconds,
                    "transcript": [],
                    "face_analysis": {},
                    "voice_analysis": {},
                    "profile": {},
                }
        return None
    finally:
        db.close()
