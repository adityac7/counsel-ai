"""Gemini Live WebSocket endpoint — minimal proxy with session resumption.

Browser connects here. We connect to Gemini. Forward everything.
On GoAway (10min connection limit), reconnect transparently using
session resumption handles. Session stays alive until browser disconnects
or counsellor ends it.
"""

import asyncio
import json
import logging
import time
from datetime import datetime, timezone

from fastapi import APIRouter
from starlette.websockets import WebSocket, WebSocketDisconnect
from google.genai import types as gt

from counselai.storage.db import get_session_factory
from counselai.storage.models import SessionStatus

from counselai.api.constants import COUNSELLOR_INSTRUCTIONS
from counselai.api.gemini_client import (
    GEMINI_LIVE_MODEL,
    build_live_config,
    get_gemini_client,
)
from counselai.settings import settings
from counselai.api.validators import validate_ws_params
from counselai.api.websocket_handler import (
    TranscriptCollector,
    browser_to_gemini,
    gemini_to_browser,
    keepalive_ping,
    session_timer,
)
from counselai.storage.repositories.live_sessions import (
    LiveSessionHandle,
    create_live_session,
    finalize_live_session,
)

logger = logging.getLogger(__name__)
router = APIRouter()

MAX_RECONNECTS = 20  # ~200 minutes max (10min per connection)


def generate_silent_audio(duration_ms: int = 100, sample_rate: int = 16000) -> bytes:
    """Generate silent PCM16 audio for triggering initial greeting."""
    n_samples = int(sample_rate * duration_ms / 1000)
    return b"\x00\x00" * n_samples


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
    is_first_connection = True
    reconnect_count = 0
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

    # Build system instruction once (sent in config, not as client_content)
    system_instruction = COUNSELLOR_INSTRUCTIONS + (
        f"\n\nStudent name: {student_name}\n"
        f"Case study / scenario:\n{scenario}"
    )

    while reconnect_count <= MAX_RECONNECTS:
        resumption_state["go_away"] = False
        config = build_live_config(
            resumption_handle=resumption_state.get("handle"),
            language=language,
            system_instruction=system_instruction if is_first_connection else "",
        )

        try:
            async with client.aio.live.connect(
                model=GEMINI_LIVE_MODEL, config=config
            ) as session:
                if is_first_connection:
                    logger.info("Connected to Gemini Live: %s", GEMINI_LIVE_MODEL)
                    await ws.send_json({"type": "setup_complete"})

                    # System prompt is now in LiveConnectConfig.system_instruction
                    # Send silent audio to trigger greeting
                    silent = generate_silent_audio()
                    await session.send_realtime_input(
                        audio=gt.Blob(data=silent, mime_type="audio/pcm")
                    )
                    logger.info("System prompt in config, silent audio sent to trigger greeting")

                    await ws.send_json({"type": "connection_active"})
                    is_first_connection = False
                else:
                    logger.info("Reconnected to Gemini (attempt %d)", reconnect_count)
                    await ws.send_json({"type": "reconnected"})

                # Run bidirectional pipeline + session timer
                b2g = asyncio.create_task(browser_to_gemini(ws, session, transcript))
                g2b = asyncio.create_task(
                    gemini_to_browser(ws, session, resumption_state, transcript)
                )
                ping = asyncio.create_task(keepalive_ping(ws))

                # Compute remaining time (accounts for reconnections)
                elapsed = time.monotonic() - session_start
                remaining = max(0, settings.max_session_duration_seconds - elapsed)
                wrapup = min(settings.session_wrapup_seconds, remaining)
                timer = asyncio.create_task(
                    session_timer(ws, session, transcript, int(remaining), int(wrapup))
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

                # If GoAway, reconnect transparently
                if resumption_state.get("go_away"):
                    reconnect_count += 1
                    logger.info(
                        "GoAway reconnect %d/%d (handle=%s)",
                        reconnect_count,
                        MAX_RECONNECTS,
                        bool(resumption_state.get("handle")),
                    )
                    continue  # Reconnect with resumption handle

                # Otherwise, session ended normally (browser disconnected)
                break

        except Exception as exc:
            logger.error("Gemini session error: %s", exc)
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
