"""Gemini Live WebSocket and transcription routes.

Reliability features:
- Connection state machine tracks CONNECTING → INITIALIZING → ACTIVE → CLOSING → CLOSED
- 30s timeout for initial Gemini connection
- Keepalive pings every 3s during init (Cloudflare drops idle connections at ~10s)
- Watchdog detects stuck sessions (>10 modelTurn without turnComplete) → force-reset
- Auto-reconnect: up to 2 retry attempts on Gemini disconnect before giving up
- Proper WebSocket close codes (1000, 1001, 1006, 1011)
"""

import asyncio
import logging

from fastapi import APIRouter, File, UploadFile, WebSocket
from fastapi.responses import JSONResponse
from google.genai import types as gt

from counselai.api.audio_utils import generate_silent_audio, transcribe_audio
from counselai.api.constants import COUNSELLOR_INSTRUCTIONS
from counselai.api.exceptions import TranscriptionError
from counselai.api.gemini_client import (
    GEMINI_LIVE_MODEL,
    build_live_config,
    get_gemini_client,
)
from counselai.api.websocket_handler import (
    ConnectionState,
    ConnectionStateMachine,
    ModelTurnWatchdog,
    _CONNECTION_TIMEOUT,
    _MAX_RECONNECT_ATTEMPTS,
    _RECONNECT_DELAY,
    _safe_send,
    browser_to_gemini,
    gemini_to_browser,
    keepalive_ping,
    safe_close,
)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/gemini-transcribe")
async def gemini_transcribe(audio: UploadFile = File(...)):
    """Transcribe audio using Gemini."""
    try:
        audio_bytes = await audio.read()
        text = await transcribe_audio(audio_bytes)
        return JSONResponse({"transcript": text})
    except TranscriptionError as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


async def _connect_and_init_gemini(
    ws: WebSocket,
    state: ConnectionStateMachine,
    config,
    scenario: str,
) -> None:
    """Connect to Gemini, send system instructions, trigger greeting, and run
    the bidirectional pipeline. Handles reconnection internally."""

    attempt = 0
    while attempt <= _MAX_RECONNECT_ATTEMPTS:
        attempt += 1
        is_reconnect = attempt > 1

        if is_reconnect:
            logger.info("[gemini] Reconnect attempt %d/%d", attempt - 1, _MAX_RECONNECT_ATTEMPTS)
            await _safe_send(ws, {
                "type": "reconnecting",
                "attempt": attempt - 1,
                "maxAttempts": _MAX_RECONNECT_ATTEMPTS,
            })
            await state.transition(ConnectionState.INITIALIZING)
            await asyncio.sleep(_RECONNECT_DELAY)

        try:
            client = get_gemini_client()

            # Wrap connection in a timeout
            try:
                connect_ctx = client.aio.live.connect(
                    model=GEMINI_LIVE_MODEL, config=config
                )
                session = await asyncio.wait_for(
                    connect_ctx.__aenter__(), timeout=_CONNECTION_TIMEOUT
                )
            except asyncio.TimeoutError:
                logger.error("[gemini] Connection timed out after %ds", _CONNECTION_TIMEOUT)
                if attempt <= _MAX_RECONNECT_ATTEMPTS:
                    continue
                await _safe_send(ws, {
                    "type": "error",
                    "message": f"Gemini connection timed out after {_CONNECTION_TIMEOUT}s",
                })
                return

            try:
                logger.info("Connected to %s (attempt %d)", GEMINI_LIVE_MODEL, attempt)
                await state.transition(ConnectionState.INITIALIZING)
                await _safe_send(ws, {"type": "setup_complete"})

                # Send system instructions
                await session.send_client_content(
                    turns=gt.Content(
                        parts=[gt.Part(text=COUNSELLOR_INSTRUCTIONS + scenario)]
                    ),
                    turn_complete=False,
                )
                logger.info("System instructions sent")

                # Send silent audio to trigger initial greeting
                silent_audio = generate_silent_audio()
                await session.send_realtime_input(
                    audio=gt.Blob(data=silent_audio, mime_type="audio/pcm")
                )
                await session.send_realtime_input(audio_stream_end=True)
                logger.info("Trigger audio sent, waiting for greeting")

                # Transition to ACTIVE
                await state.transition(ConnectionState.ACTIVE)
                await _safe_send(ws, {"type": "connection_active"})

                # Run bidirectional pipeline
                watchdog = ModelTurnWatchdog()
                b2g_task = asyncio.create_task(browser_to_gemini(ws, session, state))
                g2b_task = asyncio.create_task(gemini_to_browser(ws, session, state, watchdog))
                ping_task = asyncio.create_task(keepalive_ping(ws, state))

                done, pending = await asyncio.wait(
                    [b2g_task, g2b_task, ping_task],
                    return_when=asyncio.FIRST_COMPLETED,
                )

                # Check if gemini_to_browser returned a reason to reconnect
                reconnect_reason = None
                for task in done:
                    result = task.result() if not task.cancelled() else None
                    if isinstance(result, str):
                        reconnect_reason = result

                for task in pending:
                    task.cancel()
                # Let cancelled tasks finish
                await asyncio.gather(*pending, return_exceptions=True)

                if reconnect_reason and attempt <= _MAX_RECONNECT_ATTEMPTS:
                    logger.warning("[gemini] Pipeline exited: %s — will reconnect", reconnect_reason)
                    continue  # retry
                else:
                    return  # clean exit or out of retries

            finally:
                # Clean up the Gemini session context manager
                try:
                    await connect_ctx.__aexit__(None, None, None)
                except Exception:
                    pass

        except Exception as exc:
            logger.error("[gemini] Connection error (attempt %d): %s", attempt, exc, exc_info=True)
            if attempt <= _MAX_RECONNECT_ATTEMPTS:
                continue
            await _safe_send(ws, {"type": "error", "message": str(exc)})
            return


@router.websocket("/gemini-ws")
async def gemini_ws_proxy(ws: WebSocket):
    """WebSocket proxy: browser <-> Gemini Live API with full reliability."""
    await ws.accept()
    scenario = ws.query_params.get("scenario", "")
    config = build_live_config()
    state = ConnectionStateMachine()

    try:
        await _connect_and_init_gemini(ws, state, config, scenario)
    except Exception as exc:
        logger.error("gemini-ws top-level error: %s", exc, exc_info=True)
        await _safe_send(ws, {"type": "error", "message": str(exc)})
    finally:
        await state.transition(ConnectionState.CLOSING)
        await safe_close(ws, code=1000, reason="session ended")
        await state.transition(ConnectionState.CLOSED)
