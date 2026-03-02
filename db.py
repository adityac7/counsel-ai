import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

DB_PATH = os.path.join(os.path.dirname(__file__), "counselai.db")
_DB_LOCK = threading.Lock()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_json(value: Any) -> str:
    if value is None:
        return "{}"
    if isinstance(value, str):
        try:
            json.loads(value)
            return value
        except json.JSONDecodeError:
            return json.dumps({"value": value}, ensure_ascii=False)
    return json.dumps(value, ensure_ascii=False)


def _from_json(value: Optional[str], default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return default


def _parse_iso(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _compute_duration_seconds(start_time: Optional[str], end_time: Optional[str]) -> Optional[int]:
    start_dt = _parse_iso(start_time)
    end_dt = _parse_iso(end_time)
    if not start_dt or not end_dt:
        return None
    delta = int((end_dt - start_dt).total_seconds())
    return max(delta, 0)


def _extract_dominant_emotion(face_data: Any, profile: Any) -> str:
    if isinstance(face_data, dict):
        summary = face_data.get("summary") or {}
        emotion = summary.get("dominant_emotion")
        if emotion:
            return str(emotion)
    if isinstance(profile, dict):
        emo = profile.get("emotional_profile") or {}
        emotion = emo.get("dominant_emotion") or emo.get("emotion")
        if emotion:
            return str(emotion)
    return "unknown"


def _normalize_confidence(raw: Any) -> Optional[float]:
    try:
        val = float(raw)
    except (TypeError, ValueError):
        return None
    if val < 0:
        return None
    if val <= 1.0:
        return round(val * 100.0, 2)
    if val <= 10.0:
        return round(val * 10.0, 2)
    return round(min(val, 100.0), 2)


def _extract_confidence(profile: Any, voice_data: Any) -> Optional[float]:
    if isinstance(profile, dict):
        behavioral = profile.get("behavioral_insights") or {}
        normalized = _normalize_confidence(behavioral.get("confidence"))
        if normalized is not None:
            return normalized

    if isinstance(voice_data, dict):
        normalized = _normalize_confidence(voice_data.get("overall_confidence_score"))
        if normalized is not None:
            return normalized

    return None


def _conn() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH, check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con


def init_db() -> None:
    with _DB_LOCK:
        con = _conn()
        try:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source TEXT NOT NULL,
                    external_session_id TEXT,
                    student_name TEXT NOT NULL,
                    student_class TEXT NOT NULL,
                    student_section TEXT DEFAULT '',
                    school TEXT DEFAULT '',
                    age INTEGER,
                    session_start_time TEXT,
                    session_end_time TEXT,
                    duration_seconds INTEGER,
                    transcript_json TEXT NOT NULL,
                    face_analysis_json TEXT NOT NULL,
                    voice_analysis_json TEXT NOT NULL,
                    profile_json TEXT NOT NULL,
                    dominant_emotion TEXT DEFAULT 'unknown',
                    confidence_score REAL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            con.commit()
        finally:
            con.close()


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
    now = _now_iso()
    end_time = session_end_time or now
    start_time = session_start_time or end_time
    duration_seconds = _compute_duration_seconds(start_time, end_time)
    dominant_emotion = _extract_dominant_emotion(face_analysis, profile)
    confidence_score = _extract_confidence(profile, voice_analysis)

    with _DB_LOCK:
        con = _conn()
        try:
            cur = con.execute(
                """
                INSERT INTO sessions (
                    source,
                    external_session_id,
                    student_name,
                    student_class,
                    student_section,
                    school,
                    age,
                    session_start_time,
                    session_end_time,
                    duration_seconds,
                    transcript_json,
                    face_analysis_json,
                    voice_analysis_json,
                    profile_json,
                    dominant_emotion,
                    confidence_score,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source,
                    external_session_id,
                    str(student_info.get("name", "Student")),
                    str(student_info.get("class", "")),
                    str(student_info.get("section", "")),
                    str(student_info.get("school", "")),
                    student_info.get("age"),
                    start_time,
                    end_time,
                    duration_seconds,
                    _to_json(transcript if transcript is not None else []),
                    _to_json(face_analysis),
                    _to_json(voice_analysis),
                    _to_json(profile),
                    dominant_emotion,
                    confidence_score,
                    now,
                    now,
                ),
            )
            con.commit()
            return int(cur.lastrowid)
        finally:
            con.close()


def list_sessions() -> List[Dict[str, Any]]:
    with _DB_LOCK:
        con = _conn()
        try:
            rows = con.execute(
                """
                SELECT
                    id,
                    source,
                    student_name,
                    student_class,
                    student_section,
                    school,
                    age,
                    session_start_time,
                    session_end_time,
                    duration_seconds,
                    dominant_emotion,
                    confidence_score,
                    created_at
                FROM sessions
                ORDER BY COALESCE(session_end_time, created_at) DESC, id DESC
                """
            ).fetchall()
        finally:
            con.close()

    return [dict(row) for row in rows]


def get_session(session_id: int) -> Optional[Dict[str, Any]]:
    with _DB_LOCK:
        con = _conn()
        try:
            row = con.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        finally:
            con.close()

    if not row:
        return None

    data = dict(row)
    data["student_info"] = {
        "name": data.pop("student_name", "Student"),
        "class": data.pop("student_class", ""),
        "section": data.pop("student_section", ""),
        "school": data.pop("school", ""),
        "age": data.pop("age", None),
    }
    data["transcript"] = _from_json(data.pop("transcript_json", "[]"), [])
    data["face_analysis"] = _from_json(data.pop("face_analysis_json", "{}"), {})
    data["voice_analysis"] = _from_json(data.pop("voice_analysis_json", "{}"), {})
    data["profile"] = _from_json(data.pop("profile_json", "{}"), {})
    return data
