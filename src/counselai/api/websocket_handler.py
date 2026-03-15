"""Minimal WebSocket proxy: Browser ↔ Gemini Live.

No watchdog. No state machine. No reconnection logic.
Just forward audio/video between browser and Gemini.
Let Gemini handle silence, turns, and conversation flow.
"""

import asyncio
import base64
import json
import logging
import struct
import math

from starlette.websockets import WebSocket, WebSocketDisconnect
from google.genai import types as gt

logger = logging.getLogger(__name__)


async def browser_to_gemini(ws: WebSocket, session) -> None:
    """Forward audio/video from browser WebSocket to Gemini Live session.

    This is the ONLY authority on session lifetime. When the browser
    disconnects, the session ends. Period.
    """
    chunk_count = 0
    try:
        while True:
            raw = await ws.receive_text()
            if not raw or not raw.strip():
                continue

            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            ri = msg.get("realtimeInput", {})
            chunks = ri.get("mediaChunks", [])

            for chunk in chunks:
                mime = chunk.get("mimeType", "")
                b64data = chunk.get("data", "")
                if not b64data:
                    continue

                try:
                    decoded = base64.b64decode(b64data)
                except Exception:
                    continue

                if mime.startswith("audio/"):
                    # Forward ALL audio to Gemini — it has its own VAD
                    await session.send_realtime_input(
                        audio=gt.Blob(data=decoded, mime_type="audio/pcm")
                    )

                    # Send audio level to frontend periodically
                    chunk_count += 1
                    if chunk_count % 5 == 0:
                        level = _compute_audio_level(decoded)
                        try:
                            await ws.send_json(level)
                        except Exception:
                            pass

                elif mime.startswith("image/"):
                    await session.send_realtime_input(
                        video=gt.Blob(data=decoded, mime_type=mime)
                    )

    except WebSocketDisconnect:
        logger.info("Browser disconnected")
    except asyncio.CancelledError:
        pass
    except Exception as exc:
        logger.error("browser→gemini error: %s", exc)


async def gemini_to_browser(ws: WebSocket, session) -> None:
    """Forward Gemini responses to browser WebSocket.

    Key pattern from official docs: wrap session.receive() in while True.
    Each receive() call yields one conversational turn. When the turn
    completes (turnComplete), we loop back for the next turn.
    The session stays alive across turns.
    """
    try:
        while True:
            # Each receive() gives us one turn
            async for response in session.receive():
                # Skip setup events
                if response.setup_complete:
                    continue

                srv = response.server_content
                if not srv:
                    continue

                out = {"serverContent": {}}
                sc = out["serverContent"]

                # Model audio/text output
                if srv.model_turn and srv.model_turn.parts:
                    parts_out = []
                    for part in srv.model_turn.parts:
                        # Skip thinking tokens
                        if getattr(part, "thought", False):
                            continue
                        if part.inline_data and part.inline_data.data:
                            parts_out.append({
                                "inlineData": {
                                    "data": base64.b64encode(
                                        part.inline_data.data
                                    ).decode(),
                                    "mimeType": "audio/pcm",
                                }
                            })
                        if part.text:
                            parts_out.append({"text": part.text})

                    if parts_out:
                        sc["modelTurn"] = {"parts": parts_out}

                # Turn complete
                if srv.turn_complete:
                    sc["turnComplete"] = True

                # Transcriptions
                if srv.input_transcription:
                    t = getattr(srv.input_transcription, "text", "")
                    if t and t.strip():
                        sc["inputTranscription"] = {"text": t.strip()}

                if srv.output_transcription:
                    t = getattr(srv.output_transcription, "text", "")
                    if t and t.strip():
                        sc["outputTranscription"] = {"text": t.strip()}

                # Send to browser if we have content
                if sc:
                    try:
                        await ws.send_json(out)
                    except Exception:
                        return  # Browser gone

            # Turn ended — loop back for next turn
            # This is normal! Don't panic, don't reconnect.
            logger.debug("Turn completed, waiting for next turn...")

    except asyncio.CancelledError:
        pass
    except Exception as exc:
        logger.error("gemini→browser error: %s", exc)


async def keepalive_ping(ws: WebSocket) -> None:
    """Send periodic pings to prevent Cloudflare from killing idle WS."""
    try:
        while True:
            await asyncio.sleep(5)
            try:
                await ws.send_json({"type": "keepalive"})
            except Exception:
                return
    except asyncio.CancelledError:
        pass


def _compute_audio_level(pcm_data: bytes) -> dict:
    """Compute RMS audio level from PCM16 data."""
    if len(pcm_data) < 2:
        return {"type": "audioLevel", "rms": 0, "peak": 0, "db": -100, "isSpeech": False}

    n_samples = len(pcm_data) // 2
    samples = struct.unpack(f"<{n_samples}h", pcm_data[: n_samples * 2])

    rms = math.sqrt(sum(s * s for s in samples) / n_samples)
    peak = max(abs(s) for s in samples) if samples else 0
    db = 20 * math.log10(rms / 32768) if rms > 0 else -100

    return {
        "type": "audioLevel",
        "rms": round(rms),
        "peak": peak,
        "db": round(db, 1),
        "isSpeech": rms > 300,
    }
