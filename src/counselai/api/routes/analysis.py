"""API routes: session analysis and case studies.

The /analyze-session endpoint uses a single unified Gemini call
(unified_analyzer) for 9-dimension scoring, then runs the career
engine (pure Python) to produce career aptitude signals.
"""

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import JSONResponse

from counselai.analysis.dashboard_persistence import persist_session_analysis, add_analysis_tokens
from counselai.settings import settings
from counselai.storage.db import get_sync_session_factory, init_db
from counselai.storage.models import SessionRecord, Turn

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/case-studies")
async def get_case_studies(lang: str = "en"):
    from counselai.case_studies import get_all_case_studies
    from counselai.storage.db import get_sync_session_factory
    init_db()
    db = get_sync_session_factory()()
    try:
        all_cs = get_all_case_studies(db)
    finally:
        db.close()
    result = []
    for cs in all_cs:
        item = dict(cs)
        if lang == "hi":
            item["scenario_text_display"] = cs.get("scenario_text_hi") or cs["scenario_text"]
        else:
            item["scenario_text_display"] = cs["scenario_text"]
        result.append(item)
    return JSONResponse({"case_studies": result})


@router.post("/analyze-session")
async def analyze_session(
    video: UploadFile | None = File(None),
    transcript: str = Form("[]"),
    student_name: str = Form("Student"),
    student_class: str = Form("10"),
    student_section: str = Form(""),
    student_school: str = Form(""),
    student_age: int = Form(15),
    session_start_time: str = Form(None),
    session_end_time: str = Form(None),
    session_id: str = Form(None),
):
    try:
        transcript_data = json.loads(transcript)
    except (json.JSONDecodeError, TypeError):
        transcript_data = []

    # DB turns are authoritative when session_id is present
    if session_id:
        db_turns = _load_transcript_turns_from_session(session_id)
        if db_turns:
            transcript_data = db_turns

    if settings.debug:
        logger.debug("Transcript data (%d entries) ready for analysis", len(transcript_data))

    # Read video for multimodal analysis
    video_bytes = b""
    if video:
        video_bytes = await video.read()
        if settings.debug and len(video_bytes) > 1000:
            _save_dev_recording(video_bytes, session_id, video.content_type)

    session_end = session_end_time or datetime.now(timezone.utc).isoformat()

    has_transcripts = len(transcript_data) > 0 and any(
        e.get("text", "").strip() for e in transcript_data
    )

    session_duration = 0
    try:
        if session_start_time and session_end:
            start = datetime.fromisoformat(session_start_time.replace("Z", "+00:00"))
            end = datetime.fromisoformat(session_end.replace("Z", "+00:00"))
            session_duration = int((end - start).total_seconds())
    except Exception:
        pass

    has_duration = session_duration > 30

    if not (has_transcripts or has_duration):
        return JSONResponse(
            {"error": "Insufficient session data for analysis."},
            status_code=400,
        )

    # Load observations and case study context from DB
    observations_data = []
    segments_data = []
    case_study_text = ""
    if session_id:
        observations_data, segments_data = _load_observations_from_session(session_id)
        case_study_text = _load_case_study_context(session_id)

    # Single unified Gemini call — produces 9 dimensions + moments + snapshot
    analysis_result = {}
    try:
        from counselai.analysis.unified_analyzer import analyze_session as run_analysis

        loop = asyncio.get_running_loop()
        _video = video_bytes if len(video_bytes) > 1000 else None
        analysis_result = await asyncio.wait_for(
            loop.run_in_executor(
                None,
                lambda: run_analysis(
                    transcript_data,
                    student_name=student_name,
                    student_grade=student_class,
                    student_school=student_school,
                    case_study=case_study_text,
                    duration_seconds=session_duration,
                    video_bytes=_video,
                    observations=observations_data,
                    segments=segments_data,
                ),
            ),
            timeout=60,
        )
    except asyncio.TimeoutError:
        logger.warning("Unified analysis timed out after 60s")
        from counselai.analysis.unified_analyzer import _fallback_result
        analysis_result = _fallback_result("Timed out after 60s")
    except Exception as exc:
        logger.error("Unified analysis failed: %s", exc, exc_info=True)
        from counselai.analysis.unified_analyzer import _fallback_result
        analysis_result = _fallback_result(str(exc))

    # Run career engine on dimension scores (pure Python, no LLM)
    report_data = _build_report_data(
        analysis_result,
        transcript_data=transcript_data,
        student_name=student_name,
        student_grade=student_class,
        student_section=student_section,
        student_school=student_school,
        case_study_text=case_study_text,
        duration_seconds=session_duration,
    )

    # Persist to session record
    _persist_analysis_to_session(
        session_id,
        analysis_result,
        report_data,
        student_name=student_name,
        student_grade=student_class,
        student_section=student_section,
        student_school=student_school,
        student_age=student_age,
    )

    return JSONResponse({"report": report_data, "session_id": session_id})


def _build_report_data(
    analysis: dict,
    *,
    transcript_data: list[dict],
    student_name: str,
    student_grade: str,
    student_section: str,
    student_school: str,
    case_study_text: str,
    duration_seconds: int,
) -> dict:
    """Assemble the full report payload for the frontend.

    Combines LLM dimension scores with the career engine's pure-Python pipeline.
    """
    from counselai.analysis.career_engine import (
        score_all_careers, score_to_band, seconds_to_display, compute_session_depth,
    )

    dimensions = analysis.get("dimensions", [])

    # Extract numeric scores (list of 9 ints)
    dim_scores = [d.get("score", 1) for d in dimensions]
    while len(dim_scores) < 9:
        dim_scores.append(1)

    # Evidence flags per dimension
    evidence_flags = [d.get("evidence_sources") or [True, False, False] for d in dimensions]
    while len(evidence_flags) < 9:
        evidence_flags.append([False, False, False])

    # Add band to each dimension
    for d in dimensions:
        d["band"] = score_to_band(d.get("score", 1))

    # Compute session depth
    turn_count = len(transcript_data)
    avg_engagement = sum(dim_scores) / len(dim_scores) * 10 if dim_scores else 50
    session_depth = compute_session_depth(turn_count, duration_seconds, avg_engagement)

    # Key moments from analysis
    key_moments = analysis.get("key_moments", [])

    # Run career engine
    career_result = score_all_careers(
        dim_scores, evidence_flags, key_moments, session_depth,
    )

    # Build strengths (top 3) and growth areas (bottom 2) from dimensions
    sorted_dims = sorted(dimensions, key=lambda d: d.get("score", 0), reverse=True)
    strengths = sorted_dims[:3] if len(sorted_dims) >= 3 else sorted_dims
    growth_areas = sorted(dimensions, key=lambda d: d.get("score", 10))[:2]

    # Parse case study title from text
    case_title = ""
    case_category = ""
    if case_study_text:
        if "]" in case_study_text:
            rest = case_study_text.split("]", 1)[1].strip()
            if ":" in rest:
                case_title = rest.split(":")[0].strip()
        if not case_title:
            case_title = case_study_text[:60]

    # Risk bar
    risk_level = analysis.get("risk_assessment", {}).get("level", "none")
    risk_flags = analysis.get("risk_assessment", {}).get("flags", [])
    risk_color_map = {"none": "green", "low": "yellow", "moderate": "orange", "high": "red", "critical": "red"}
    risk_color = risk_color_map.get(risk_level, "green")
    if risk_flags:
        risk_text = "; ".join(f.get("reason", f.get("key", "")) for f in risk_flags)
    elif risk_level == "none":
        risk_text = "No risk flags identified. Protective factors present."
    else:
        risk_text = f"Risk level: {risk_level}"

    # Format career matches for frontend (camelCase keys)
    def fmt_career(c, idx=0):
        ev = c.get("evidence")
        return {
            "name": c["name"],
            "category": c["category"],
            "compositeScore": c["composite"],
            "fitScore": c["fit"],
            "shapeScore": c["shape"],
            "confidenceLabel": c["confidence_label"],
            "strongDims": c["strong_dims"],
            "gapDim": c["gap_dim"],
            "activeSynergies": c["career_synergies"],
            "evidenceQuote": ev.get("quote", "") if ev else "",
            "evidenceTurn": ev.get("turn", 0) if ev else 0,
        }

    # Format dimensions for frontend (camelCase)
    def fmt_dim(d):
        return {
            "name": d.get("name", ""),
            "domain": d.get("domain", ""),
            "score": d.get("score", 1),
            "band": d.get("band", "Emerging"),
            "because": d.get("because", ""),
            "keyMomentQuote": d.get("key_moment_quote", ""),
            "keyMomentTurn": d.get("key_moment_turn", 0),
            "keyMomentTime": "",
            "growthTip": d.get("growth_tip", ""),
            "evidenceSources": d.get("evidence_sources", [True, False, False]),
        }

    def fmt_moment(m):
        return {
            "turn": m.get("turn", 0),
            "time": "",
            "quote": m.get("quote", ""),
            "audioSignal": m.get("audio_signal", ""),
            "insight": m.get("insight", ""),
        }

    return {
        "student": {
            "name": student_name,
            "class_num": student_grade,
            "section": student_section,
            "school": student_school,
        },
        "caseStudy": {
            "title": case_title,
            "category": case_category,
            "targetClass": f"Class {student_grade}",
        },
        "sessionDate": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "durationDisplay": seconds_to_display(duration_seconds),
        "turnCount": turn_count,
        "sessionDepth": session_depth,
        "snapshotText": analysis.get("snapshot", ""),
        "riskLevel": risk_color,
        "riskText": risk_text,
        "dimensions": [fmt_dim(d) for d in dimensions],
        "keyMoments": [fmt_moment(m) for m in key_moments],
        "strengths": [fmt_dim(d) for d in strengths],
        "growthAreas": [fmt_dim(d) for d in growth_areas],
        "nextSessionRec": analysis.get("next_session_rec", ""),
        "sessionSummary": analysis.get("session_summary", ""),
        "studentView": analysis.get("student_view", {}),
        "followUp": analysis.get("follow_up", {}),
        "careerCount": len(career_result["ranked"]),
        "careerMatches": [fmt_career(c, i) for i, c in enumerate(career_result["top_matches"])],
        "allCareers": [fmt_career(c, i) for i, c in enumerate(career_result["ranked"])],
        "synergies": [
            {"name": s["name"], "description": s["desc"], "active": s["active"]}
            for s in career_result["synergies"]
        ],
        "streams": career_result["streams"],
        "activeSynergyNames": career_result["active_synergy_names"],
        # Raw analysis for dashboard persistence
        "_raw_analysis": analysis,
    }


def _save_dev_recording(video_bytes: bytes, session_id: str | None, content_type: str | None) -> None:
    try:
        ext = "webm"
        if content_type and "/" in content_type:
            ext = content_type.split("/")[1].split(";")[0].strip() or "webm"
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        sid = (session_id or "nosession")[:8]
        out_dir = Path("dev_recordings")
        out_dir.mkdir(exist_ok=True)
        out_path = out_dir / f"{ts}_{sid}.{ext}"
        out_path.write_bytes(video_bytes)
        logger.info("[DEV] Saved session recording: %s (%d KB)", out_path, len(video_bytes) // 1024)
    except Exception as exc:
        logger.warning("[DEV] Could not save recording: %s", exc)


def _load_case_study_context(session_id: str | None) -> str:
    if not session_id:
        return ""
    try:
        init_db()
        factory = get_sync_session_factory()
        db = factory()
        try:
            sid = uuid.UUID(session_id)
            session = db.get(SessionRecord, sid)
            if session is None or not session.case_study_id:
                return ""
            from counselai.case_studies import get_all_case_studies
            all_cs = get_all_case_studies(db)
            for cs in all_cs:
                if cs.get("id") == session.case_study_id:
                    return f"[{cs['id']}] {cs.get('title', '')}: {cs.get('scenario_text', '')}"
            return f"Case study ID: {session.case_study_id}"
        finally:
            db.close()
    except Exception as exc:
        logger.warning("Failed to load case study for session %s: %s", session_id, exc)
        return ""


def _load_observations_from_session(session_id: str | None) -> tuple[list[dict], list[dict]]:
    if not session_id:
        return [], []
    try:
        init_db()
        factory = get_sync_session_factory()
        db = factory()
        try:
            sid = uuid.UUID(session_id)
            session = db.get(SessionRecord, sid)
            if session is None:
                return [], []
            return session.observations_json or [], session.segments_json or []
        finally:
            db.close()
    except Exception as exc:
        logger.warning("Failed to load observations for session %s: %s", session_id, exc)
        return [], []


def _load_transcript_turns_from_session(session_id: str | None) -> list[dict]:
    if not session_id:
        return []
    try:
        init_db()
        factory = get_sync_session_factory()
        db = factory()
        try:
            sid = uuid.UUID(session_id)
            turns = (
                db.query(Turn)
                .filter(Turn.session_id == sid)
                .order_by(Turn.turn_index.asc())
                .all()
            )
            return [
                {"role": t.speaker, "text": t.text}
                for t in turns
                if t.text and t.text.strip()
            ]
        finally:
            db.close()
    except Exception as exc:
        logger.warning("Failed to load fallback transcript for session %s: %s", session_id, exc)
        return []


def _persist_analysis_to_session(
    session_id: str | None,
    analysis_result: dict,
    report_data: dict,
    *,
    student_name: str,
    student_grade: str,
    student_section: str,
    student_school: str,
    student_age: int,
) -> None:
    """Save the unified analysis to an existing SessionRecord."""
    if not session_id:
        logger.warning("No session_id provided — analysis not persisted to DB")
        return

    try:
        init_db()
        factory = get_sync_session_factory()
        db = factory()
        try:
            sid = uuid.UUID(session_id)

            # Build dashboard payload from dimension-based analysis
            dimensions = analysis_result.get("dimensions", [])
            dashboard_payload = {
                "counsellor_view": {
                    "summary": analysis_result.get("session_summary", ""),
                    "constructs": [
                        {
                            "key": d.get("name", "").lower().replace(" ", "_").replace("&", "and"),
                            "label": d.get("name", ""),
                            "score": d.get("score", 1) / 10.0,  # normalize to 0-1
                            "status": "supported" if d.get("score", 1) >= 7 else "mixed" if d.get("score", 1) >= 4 else "weak",
                            "evidence_summary": d.get("because", ""),
                        }
                        for d in dimensions
                    ],
                    "cross_modal_notes": [],
                    "follow_up": analysis_result.get("follow_up", {}),
                },
                "student_view": analysis_result.get("student_view", {}),
                "school_view": {"themes": [], "academic_pressure_level": "none"},
                "hypotheses": [
                    {
                        "construct_key": d.get("name", "").lower().replace(" ", "_").replace("&", "and"),
                        "label": d.get("name", ""),
                        "score": d.get("score", 1) / 10.0,
                        "status": "supported" if d.get("score", 1) >= 7 else "mixed" if d.get("score", 1) >= 4 else "weak",
                        "evidence_summary": d.get("because", ""),
                    }
                    for d in dimensions
                ],
                "red_flags": [
                    {"key": f.get("key", ""), "severity": f.get("severity", "medium"), "reason": f.get("reason", "")}
                    for f in analysis_result.get("risk_assessment", {}).get("flags", [])
                ],
            }

            # Strip _raw_analysis before storing (it's redundant)
            clean_report = {k: v for k, v in report_data.items() if k != "_raw_analysis"}

            persisted = persist_session_analysis(
                db,
                session_id=sid,
                report_data=clean_report,
                dashboard_payload=dashboard_payload,
                student_name=student_name,
                student_grade=student_grade,
                student_section=student_section,
                student_school=student_school,
                student_age=student_age,
            )
            if not persisted:
                logger.warning("Session %s not found — cannot persist analysis", session_id)
                return

            db.commit()
            logger.info("Unified analysis persisted to session %s", session_id)

            # Persist analysis-call token usage (additive on top of live session tokens)
            usage = analysis_result.get("_analysis_usage", {})
            if usage.get("input_tokens") or usage.get("output_tokens"):
                try:
                    from counselai.api.gemini_client import GEMINI_ANALYSIS_MODEL
                    add_analysis_tokens(
                        db,
                        session_id=sid,
                        input_tokens=usage.get("input_tokens", 0),
                        output_tokens=usage.get("output_tokens", 0),
                        model=GEMINI_ANALYSIS_MODEL,
                    )
                    db.commit()
                except Exception as exc:
                    db.rollback()
                    logger.warning("Failed to persist analysis tokens for %s: %s", session_id, exc)
        except Exception as exc:
            db.rollback()
            logger.error("Failed to persist analysis: %s", exc)
        finally:
            db.close()
    except Exception as exc:
        logger.error("Failed to persist analysis (outer): %s", exc)
