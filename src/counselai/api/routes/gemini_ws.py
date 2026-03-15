"""Gemini Live WebSocket endpoint — minimal proxy.

Browser connects here. We connect to Gemini. Forward everything.
No reconnection. No watchdog. No state machine.
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


def generate_silent_audio(duration_ms: int = 100, sample_rate: int = 16000) -> bytes:
    """Generate silent PCM16 audio for triggering initial greeting."""
    n_samples = int(sample_rate * duration_ms / 1000)
    return b"\x00\x00" * n_samples


@router.websocket("/gemini-ws")
async def gemini_ws_proxy(ws: WebSocket) -> None:
    """Main WebSocket handler — connects browser to Gemini Live."""
    await ws.accept()
    logger.info("Browser connected")

    # Get scenario and student name from query params
    scenario = ws.query_params.get("scenario", "General counselling session")
    student_name = ws.query_params.get("name", "Student")

    client = get_gemini_client()
    config = build_live_config()

    try:
        async with client.aio.live.connect(
            model=GEMINI_LIVE_MODEL, config=config
        ) as session:
            logger.info("Connected to Gemini Live: %s", GEMINI_LIVE_MODEL)

            # Tell browser we're ready
            await ws.send_json({"type": "setup_complete"})

            # Send system instructions
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

            # Tell browser we're active
            await ws.send_json({"type": "connection_active"})

            # Run bidirectional pipeline
            b2g = asyncio.create_task(browser_to_gemini(ws, session))
            g2b = asyncio.create_task(gemini_to_browser(ws, session))
            ping = asyncio.create_task(keepalive_ping(ws))

            # Wait for browser to disconnect (b2g is the authority)
            done, pending = await asyncio.wait(
                [b2g, g2b, ping],
                return_when=asyncio.FIRST_COMPLETED,
            )

            # Log what ended
            for task in done:
                name = {id(b2g): "browser→gemini", id(g2b): "gemini→browser", id(ping): "keepalive"}.get(id(task), "?")
                exc = task.exception() if not task.cancelled() else None
                logger.info("Pipeline ended: %s (exc=%s)", name, exc)

            # Cancel remaining tasks
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)

    except Exception as exc:
        logger.error("Gemini session error: %s", exc)
        try:
            await ws.send_json({"type": "error", "message": str(exc)})
        except Exception:
            pass

    # Close browser WebSocket
    try:
        await ws.close(1000, "Session ended")
    except Exception:
        pass
    logger.info("Session closed")
