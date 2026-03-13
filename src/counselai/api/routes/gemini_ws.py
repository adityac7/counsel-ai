"""Gemini Live WebSocket and transcription routes."""

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
    browser_to_gemini,
    gemini_to_browser,
    keepalive_ping,
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


@router.websocket("/gemini-ws")
async def gemini_ws_proxy(ws: WebSocket):
    """WebSocket proxy: browser <-> Gemini Live API using official SDK."""
    await ws.accept()
    scenario = ws.query_params.get("scenario", "")

    config = build_live_config()

    try:
        client = get_gemini_client()
        async with client.aio.live.connect(
            model=GEMINI_LIVE_MODEL, config=config
        ) as session:
            logger.info("Connected to %s with audio output", GEMINI_LIVE_MODEL)
            await ws.send_json({"type": "setup_complete"})

            # Send system instructions via client content
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

            # Run bidirectional tasks + keepalive
            done, pending = await asyncio.wait(
                [
                    asyncio.create_task(browser_to_gemini(ws, session)),
                    asyncio.create_task(gemini_to_browser(ws, session)),
                    asyncio.create_task(keepalive_ping(ws)),
                ],
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()

    except Exception as exc:
        logger.error("gemini-ws error: %s", exc, exc_info=True)
        try:
            await ws.send_json({"type": "error", "message": str(exc)})
        except Exception:
            pass
    finally:
        try:
            await ws.close()
        except Exception:
            pass
