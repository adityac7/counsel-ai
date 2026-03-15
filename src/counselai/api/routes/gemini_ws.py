"""Gemini Live WebSocket endpoint — minimal proxy with session resumption.

Browser connects here. We connect to Gemini. Forward everything.
On GoAway (10min connection limit), reconnect transparently using
session resumption handles. Session stays alive until browser disconnects
or counsellor ends it.
"""

import asyncio
import logging

from fastapi import APIRouter
from starlette.websockets import WebSocket, WebSocketDisconnect
from google.genai import types as gt

from counselai.api.constants import COUNSELLOR_INSTRUCTIONS
from counselai.api.gemini_client import (
    GEMINI_LIVE_MODEL,
    build_live_config,
    get_gemini_client,
)
from counselai.api.websocket_handler import (
    browser_to_gemini,
    gemini_to_browser,
    keepalive_ping,
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

    scenario = ws.query_params.get("scenario", "General counselling session")
    student_name = ws.query_params.get("name", "Student")

    client = get_gemini_client()
    resumption_state = {"handle": None, "go_away": False}
    is_first_connection = True
    reconnect_count = 0

    while reconnect_count <= MAX_RECONNECTS:
        resumption_state["go_away"] = False
        config = build_live_config(resumption_handle=resumption_state.get("handle"))

        try:
            async with client.aio.live.connect(
                model=GEMINI_LIVE_MODEL, config=config
            ) as session:
                if is_first_connection:
                    logger.info("Connected to Gemini Live: %s", GEMINI_LIVE_MODEL)
                    await ws.send_json({"type": "setup_complete"})

                    # Send system instructions (only on first connection)
                    prompt = COUNSELLOR_INSTRUCTIONS + (
                        f"\n\nStudent name: {student_name}\n"
                        f"Case study / scenario:\n{scenario}"
                    )
                    await session.send_client_content(
                        turns=gt.Content(parts=[gt.Part(text=prompt)]),
                        turn_complete=True,
                    )
                    logger.info("System prompt sent")

                    # Send silent audio to trigger greeting
                    silent = generate_silent_audio()
                    await session.send_realtime_input(
                        audio=gt.Blob(data=silent, mime_type="audio/pcm")
                    )

                    await ws.send_json({"type": "connection_active"})
                    is_first_connection = False
                else:
                    logger.info("Reconnected to Gemini (attempt %d)", reconnect_count)
                    await ws.send_json({"type": "reconnected"})

                # Run bidirectional pipeline
                b2g = asyncio.create_task(browser_to_gemini(ws, session))
                g2b = asyncio.create_task(
                    gemini_to_browser(ws, session, resumption_state)
                )
                ping = asyncio.create_task(keepalive_ping(ws))

                done, pending = await asyncio.wait(
                    [b2g, g2b, ping],
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
            try:
                await ws.send_json({"type": "error", "message": str(exc)})
            except Exception:
                pass
            break

    # Close browser WebSocket
    try:
        await ws.close(1000, "Session ended")
    except Exception:
        pass
    logger.info("Session closed (reconnects: %d)", reconnect_count)
