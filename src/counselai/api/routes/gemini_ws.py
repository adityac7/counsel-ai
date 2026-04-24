"""Gemini Live WebSocket endpoint — minimal proxy with session resumption.

Browser connects here. We connect to Gemini. Forward everything.
On GoAway (10min connection limit), reconnect transparently using
session resumption handles. Session stays alive until browser disconnects
or counsellor ends it.
"""

import asyncio
import logging
import time
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter
from starlette.websockets import WebSocket, WebSocketDisconnect
from google.genai import types as gt

from counselai.analysis.dashboard_persistence import persist_session_usage
from counselai.storage.db import get_session_factory, get_sync_session_factory
from counselai.storage.models import SessionStatus

from counselai.api.constants import get_counsellor_instructions
from counselai.api.gemini_client import (
    GEMINI_LIVE_MODEL,
    build_live_config,
    get_gemini_client,
)
from counselai.settings import settings
from counselai.api.validators import validate_ws_params
from counselai.api.websocket_handler import (
    TranscriptCollector,
    UsageAccumulator,
    browser_to_gemini,
    gemini_to_browser,
    keepalive_ping,
    session_timer,
)
from counselai.storage.live_sessions import (
    LiveSessionHandle,
    create_live_session,
    finalize_live_session,
)

logger = logging.getLogger(__name__)
router = APIRouter()

MAX_RECONNECTS = 20  # ~200 minutes max (10min per connection)


def _persist_usage_safely(session_id: str, usage_agg) -> None:
    """Upsert the session's token usage row. Never raises.

    Runs synchronously — ``persist_session_usage`` uses a sync SQLAlchemy
    session. Called from the websocket handler at session-end; if anything
    goes wrong we log and move on so the session finalizer still returns.
    """
    try:
        sid = uuid.UUID(session_id)
    except (ValueError, TypeError, AttributeError):
        logger.warning("Usage persist skipped — bad session_id %r", session_id)
        return
    try:
        factory = get_sync_session_factory()
        db = factory()
        try:
            persist_session_usage(
                db,
                session_id=sid,
                input_tokens=usage_agg.input_tokens,
                output_tokens=usage_agg.output_tokens,
                cached_tokens=usage_agg.cached_tokens,
                total_tokens=usage_agg.total_tokens,
                model=settings.gemini_live_model,
                input_modality=usage_agg.input_modality or None,
                output_modality=usage_agg.output_modality or None,
            )
            db.commit()
        except Exception as exc:
            db.rollback()
            logger.warning("Failed to persist session usage for %s: %s", session_id, exc)
        finally:
            db.close()
    except Exception as exc:
        logger.warning("Failed to open sync session for usage persist: %s", exc)


@router.websocket("/gemini-ws")
async def gemini_ws_proxy(ws: WebSocket) -> None:
    """Main WebSocket handler — connects browser to Gemini Live.

    Supports transparent reconnection on GoAway signals.
    Session duration: unlimited (context_window_compression + session_resumption).
    """
    await ws.accept()
    logger.info("Browser connected")

    params = validate_ws_params(dict(ws.query_params))
    scenario = params["scenario"]
    student_name = params["name"]
    language = params["lang"]

    try:
        client = get_gemini_client()
    except Exception as exc:
        logger.error("Gemini client unavailable: %s", exc)
        try:
            await ws.send_json({
                "type": "error",
                "message": "Gemini API is not configured. Please set GEMINI_API_KEY.",
                "reconnect_failed": True,
            })
            await ws.close(1011, "Provider unavailable")
        except Exception:
            pass
        return
    resumption_state = {"handle": None, "go_away": False}
    transcript = TranscriptCollector()
    usage_agg = UsageAccumulator()
    is_first_connection = True
    reconnect_count = 0
    transient_error_count = 0
    MAX_TRANSIENT_RETRIES = 3
    session_start = time.monotonic()
    live_session: LiveSessionHandle | None = None
    final_status = SessionStatus.completed

    try:
        async with get_session_factory()() as db:
            live_session = await create_live_session(
                db,
                student_name=student_name,
                student_grade=params["grade"],
                student_section=params["section"],
                school_name=params["school"],
                student_age=params["age"],
                scenario=scenario,
                case_study_id=params.get("case_study_id"),
                language=language,
            )
    except Exception as exc:
        logger.error("Failed to create live session row: %s", exc, exc_info=True)
        try:
            await ws.send_json({
                "type": "error",
                "message": "Session could not be initialized. Please try again.",
                "reconnect_failed": True,
            })
            await ws.close(1011, "Session persistence unavailable")
        except Exception:
            pass
        return

    try:
        await ws.send_json({
            "type": "session_started",
            "session_id": live_session.session_id,
            "started_at": live_session.started_at.isoformat(),
        })
    except Exception:
        logger.warning("Failed to notify browser of session start", exc_info=True)

    # System instruction is the shrunk counsellor persona only — no scenario,
    # no student name. Per-session context is injected as the first user turn
    # below so the system prompt can stay cache-friendly.
    system_instruction = get_counsellor_instructions(language)

    while reconnect_count <= MAX_RECONNECTS:
        resumption_state["go_away"] = False
        config = build_live_config(
            resumption_handle=resumption_state.get("handle"),
            language=language,
            system_instruction=system_instruction if is_first_connection else "",
        )

        _t_connect_start = time.monotonic()
        try:
            async with client.aio.live.connect(
                model=GEMINI_LIVE_MODEL, config=config
            ) as session:
                _t_connected = time.monotonic()
                if is_first_connection:
                    logger.info(
                        "⏱ [phase=connect] Gemini Live handshake: %.0fms (model=%s, system_prompt=YES)",
                        (_t_connected - _t_connect_start) * 1000,
                        GEMINI_LIVE_MODEL,
                    )
                    await ws.send_json({"type": "setup_complete"})

                    # Inject per-session context (student + scenario) as the
                    # first user turn. turn_complete=True forces Gemini to
                    # take the next turn — i.e. produce the greeting — without
                    # needing a silent-audio hack.
                    _t_content_send = time.monotonic()
                    await session.send_client_content(
                        turns=gt.Content(
                            role="user",
                            parts=[gt.Part(text=(
                                f"Student: {student_name}\n\n"
                                f"Scenario:\n{scenario}\n\n"
                                "Greet the student and begin the interview."
                            ))],
                        ),
                        turn_complete=True,
                    )
                    logger.info(
                        "⏱ [phase=greeting] Context+greeting sent (scenario_chars=%d, student=%r)",
                        len(scenario), student_name,
                    )
                    logger.info(
                        "⏱ [phase=greeting] send_client_content took: %.0fms",
                        (time.monotonic() - _t_content_send) * 1000,
                    )

                    await ws.send_json({"type": "connection_active"})
                    is_first_connection = False
                else:
                    logger.info(
                        "⏱ [phase=reconnect] Reconnected to Gemini (attempt %d, handshake=%.0fms, system_prompt=NO, resumption=%s)",
                        reconnect_count,
                        (_t_connected - _t_connect_start) * 1000,
                        bool(resumption_state.get("handle")),
                    )
                    await ws.send_json({"type": "reconnected"})

                # Run bidirectional pipeline + session timer
                b2g = asyncio.create_task(browser_to_gemini(ws, session, transcript))
                g2b = asyncio.create_task(
                    gemini_to_browser(ws, session, resumption_state, transcript, language, usage_agg)
                )
                ping = asyncio.create_task(keepalive_ping(ws))

                # Compute remaining time (accounts for reconnections)
                elapsed = time.monotonic() - session_start
                remaining = max(0, settings.max_session_duration_seconds - elapsed)
                wrapup = min(settings.session_wrapup_seconds, remaining)
                timer = asyncio.create_task(
                    session_timer(ws, session, transcript, int(remaining), int(wrapup), language)
                )

                done, pending = await asyncio.wait(
                    [b2g, g2b, ping, timer],
                    return_when=asyncio.FIRST_COMPLETED,
                )

                for task in done:
                    name = {
                        id(b2g): "browser→gemini",
                        id(g2b): "gemini→browser",
                        id(ping): "keepalive",
                    }.get(id(task), "?")
                    exc = task.exception() if not task.cancelled() else None
                    logger.info("Pipeline ended: %s (exc=%s)", name, exc)

                for task in pending:
                    task.cancel()
                await asyncio.gather(*pending, return_exceptions=True)

                # Handle explicit end_session or transient error from browser→gemini
                if b2g in done and not b2g.cancelled() and b2g.exception() is None:
                    result = b2g.result()
                    if result == "transient_error":
                        transient_error_count += 1
                        backoff = min(2 ** transient_error_count, 8)
                        has_handle = bool(resumption_state.get("handle"))
                        logger.warning(
                            "⏱ [phase=retry] Gemini transient error %d/%d — retrying in %ds "
                            "(resumption=%s, turns_so_far=%d)",
                            transient_error_count, MAX_TRANSIENT_RETRIES, backoff,
                            has_handle, len(transcript.turns),
                        )
                        if transient_error_count <= MAX_TRANSIENT_RETRIES:
                            # Keep the resumption handle if we have one — session resumption
                            # is designed exactly for unexpected drops like 1011 errors.
                            # Only if there's no handle (crashed before one was issued) do we
                            # need to re-bootstrap from scratch via is_first_connection.
                            if not has_handle:
                                logger.warning(
                                    "⏱ No resumption handle — will re-bootstrap with system prompt + greeting"
                                )
                                is_first_connection = True
                            await asyncio.sleep(backoff)
                            try:
                                await ws.send_json({
                                    "type": "reconnecting",
                                    "attempt": transient_error_count,
                                    "maxAttempts": MAX_TRANSIENT_RETRIES,
                                })
                            except Exception:
                                pass
                            continue
                        else:
                            logger.error("⏱ Transient error limit reached — giving up")
                            final_status = SessionStatus.failed
                            try:
                                await ws.send_json({
                                    "type": "error",
                                    "message": "Gemini service is temporarily unavailable. Please try again.",
                                    "reconnect_failed": True,
                                })
                            except Exception:
                                pass
                            break
                    if result == "end_session":
                        logger.info("Graceful end_session — finalizing now")
                        transcript.flush()
                        if live_session is not None:
                            try:
                                async with get_session_factory()() as db:
                                    saved_session_id = await finalize_live_session(
                                        db,
                                        session_id=live_session.session_id,
                                        turns=transcript.turns,
                                        observations=transcript.observations,
                                        segments=transcript.segments,
                                        status=final_status,
                                        ended_at=datetime.now(timezone.utc),
                                    )
                                if saved_session_id:
                                    _persist_usage_safely(saved_session_id, usage_agg)
                                    try:
                                        await ws.send_json({"type": "session_saved", "session_id": saved_session_id})
                                    except Exception:
                                        pass
                                    # Mark as already finalized so we skip the post-loop finalize
                                    live_session = None
                            except Exception as exc:
                                logger.error("Failed to finalize on end_session: %s", exc, exc_info=True)
                        try:
                            await ws.close(1000, "Session ended")
                        except Exception:
                            pass
                        return

                # If GoAway, reconnect transparently
                if resumption_state.get("go_away"):
                    reconnect_count += 1
                    logger.info(
                        "GoAway reconnect %d/%d (handle=%s)",
                        reconnect_count,
                        MAX_RECONNECTS,
                        bool(resumption_state.get("handle")),
                    )
                    if reconnect_count > MAX_RECONNECTS:
                        logger.error("Reconnect attempts exhausted (%d)", MAX_RECONNECTS)
                        final_status = SessionStatus.failed
                        break
                    continue  # Reconnect with resumption handle

                # Otherwise, session ended normally (browser disconnected)
                break

        except Exception as exc:
            exc_str = str(exc)
            is_transient = "1011" in exc_str or "internal error" in exc_str.lower()
            if is_transient and transient_error_count < MAX_TRANSIENT_RETRIES:
                transient_error_count += 1
                backoff = min(2 ** transient_error_count, 8)
                has_handle = bool(resumption_state.get("handle"))
                logger.warning(
                    "⏱ [phase=retry] Gemini transient error (outer) %d/%d — retrying in %ds "
                    "(resumption=%s): %s",
                    transient_error_count, MAX_TRANSIENT_RETRIES, backoff, has_handle, exc,
                )
                if not has_handle:
                    is_first_connection = True
                await asyncio.sleep(backoff)
                try:
                    await ws.send_json({
                        "type": "reconnecting",
                        "attempt": transient_error_count,
                        "maxAttempts": MAX_TRANSIENT_RETRIES,
                    })
                except Exception:
                    pass
                continue
            logger.error("⏱ Gemini session error (fatal): %s", exc)
            final_status = SessionStatus.failed
            transcript.flush()
            try:
                await ws.send_json({
                    "type": "error",
                    "message": str(exc),
                    "reconnect_failed": True,
                    "turns_saved": len(transcript.turns),
                })
            except Exception:
                pass
            break

    # Save transcript to DB
    transcript.flush()
    saved_session_id = None
    if live_session is not None:
        try:
            async with get_session_factory()() as db:
                saved_session_id = await finalize_live_session(
                    db,
                    session_id=live_session.session_id,
                    turns=transcript.turns,
                    observations=transcript.observations,
                    segments=transcript.segments,
                    status=final_status,
                    ended_at=datetime.now(timezone.utc),
                )
        except Exception as exc:
            logger.error("Failed to finalize live session %s: %s", live_session.session_id, exc, exc_info=True)

    if saved_session_id:
        _persist_usage_safely(saved_session_id, usage_agg)

    # Best-effort compatibility event for older clients that still listen for it.
    if saved_session_id:
        try:
            await ws.send_json({"type": "session_saved", "session_id": saved_session_id})
        except Exception:
            logger.info("Browser closed before session_saved could be delivered")

    # Close browser WebSocket
    try:
        await ws.close(1000, "Session ended")
    except Exception:
        pass
    logger.info("Session closed (reconnects: %d, turns: %d)", reconnect_count, len(transcript.turns))
