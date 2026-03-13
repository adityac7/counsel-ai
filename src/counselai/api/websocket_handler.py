"""WebSocket message handling for Gemini Live sessions.

Manages the bidirectional browser <-> Gemini pipeline:
- browser_to_gemini: receives audio/video from browser, forwards to Gemini
- gemini_to_browser: receives model output, forwards to browser
"""

import asyncio
import base64
import json
import logging

from google.genai import types as gt
from starlette.websockets import WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

# Keepalive interval in seconds
_KEEPALIVE_INTERVAL = 15


async def browser_to_gemini(ws: WebSocket, session) -> None:
    """Forward audio/video chunks from the browser WebSocket to Gemini.

    Expects JSON messages with the structure:
        {"realtimeInput": {"mediaChunks": [{"mimeType": "...", "data": "base64..."}]}}
    """
    try:
        while True:
            raw = await ws.receive_text()
            if not raw or not raw.strip():
                continue
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                logger.warning("Invalid JSON from browser, skipping")
                continue

            ri = msg.get("realtimeInput", {})
            chunks = ri.get("mediaChunks", [])
            for chunk in chunks:
                mime = chunk.get("mimeType", "")
                b64data = chunk.get("data", "")
                if not b64data:
                    continue
                decoded = base64.b64decode(b64data)
                if mime.startswith("audio/"):
                    await session.send_realtime_input(
                        audio=gt.Blob(data=decoded, mime_type="audio/pcm")
                    )
                elif mime.startswith("image/"):
                    await session.send_realtime_input(
                        video=gt.Blob(data=decoded, mime_type=mime)
                    )
    except WebSocketDisconnect:
        logger.info("Browser disconnected")
    except asyncio.CancelledError:
        pass
    except Exception as exc:
        logger.error("browser->gemini error: %s", exc)


async def gemini_to_browser(ws: WebSocket, session) -> None:
    """Forward Gemini model output to the browser WebSocket.

    Handles audio data, text, transcriptions, turn completion,
    and generation completion events. Filters out thinking tokens.
    """
    try:
        async for response in session.receive():
            # Skip setup_complete events
            if response.setup_complete:
                continue

            out: dict = {"serverContent": {}}
            sc = out["serverContent"]
            srv = response.server_content

            audio_data = None
            text_data = None

            if srv and srv.model_turn and srv.model_turn.parts:
                for part in srv.model_turn.parts:
                    # Filter out thinking tokens (part.thought == True)
                    if getattr(part, "thought", False):
                        continue
                    if part.inline_data and part.inline_data.data:
                        audio_data = part.inline_data.data
                    if part.text:
                        text_data = part.text

            if audio_data:
                sc["modelTurn"] = {
                    "parts": [
                        {
                            "inlineData": {
                                "data": base64.b64encode(audio_data).decode(),
                                "mimeType": "audio/pcm",
                            }
                        }
                    ]
                }

            if text_data:
                if "modelTurn" not in sc:
                    sc["modelTurn"] = {"parts": []}
                sc["modelTurn"]["parts"].append({"text": text_data})

            if srv:
                if srv.turn_complete:
                    sc["turnComplete"] = True
                if srv.input_transcription:
                    t = getattr(srv.input_transcription, "text", "")
                    if t and t.strip():
                        sc["inputTranscription"] = {"text": t.strip()}
                if srv.output_transcription:
                    t = getattr(srv.output_transcription, "text", "")
                    if t and t.strip():
                        sc["outputTranscription"] = {"text": t.strip()}
                if srv.generation_complete:
                    sc["generationComplete"] = True

            # Only send if we have actual content
            if sc:
                await ws.send_json(out)

    except asyncio.CancelledError:
        pass
    except Exception as exc:
        logger.error("gemini->browser error: %s", exc)


async def keepalive_ping(ws: WebSocket) -> None:
    """Send periodic keepalive pings to prevent WebSocket timeout."""
    try:
        while True:
            await asyncio.sleep(_KEEPALIVE_INTERVAL)
            await ws.send_json({"type": "keepalive"})
    except asyncio.CancelledError:
        pass
    except Exception:
        pass  # Connection closed, exit silently
