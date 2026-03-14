"""WebSocket message handling for Gemini Live sessions.

Manages the bidirectional browser <-> Gemini pipeline with reliability:
- Connection state machine: CONNECTING → INITIALIZING → ACTIVE → CLOSING → CLOSED
- Keepalive pings every 3s during Gemini init (Cloudflare drops idle connections)
- Watchdog: detect >10 consecutive modelTurn events without turnComplete → force-reset
- Proper WebSocket close code handling (1000, 1001, 1006, 1011)
- Reconnection logic for Gemini disconnects
"""

import asyncio
import base64
import enum
import json
import logging
import time

from google.genai import types as gt
from starlette.websockets import WebSocket, WebSocketDisconnect, WebSocketState

from counselai.api.audio_utils import (
    compute_audio_level,
    is_speech,
    validate_pcm_format,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_KEEPALIVE_INTERVAL_INIT = 3  # seconds — fast pings during Gemini init
_KEEPALIVE_INTERVAL_ACTIVE = 15  # seconds — normal pings once active
_WATCHDOG_MAX_MODEL_TURNS = 10  # consecutive modelTurn events without turnComplete
_CONNECTION_TIMEOUT = 30  # seconds — max wait for initial Gemini connection
_MAX_RECONNECT_ATTEMPTS = 2
_RECONNECT_DELAY = 1.0  # seconds between reconnect attempts

# How often to send audio level updates to the frontend (every N chunks)
_LEVEL_METER_INTERVAL = 3


# ---------------------------------------------------------------------------
# Connection State Machine
# ---------------------------------------------------------------------------
class ConnectionState(enum.Enum):
    CONNECTING = "CONNECTING"
    INITIALIZING = "INITIALIZING"
    ACTIVE = "ACTIVE"
    CLOSING = "CLOSING"
    CLOSED = "CLOSED"


class ConnectionStateMachine:
    """Track and enforce WebSocket connection state transitions."""

    _VALID_TRANSITIONS = {
        ConnectionState.CONNECTING: {ConnectionState.INITIALIZING, ConnectionState.CLOSING, ConnectionState.CLOSED},
        ConnectionState.INITIALIZING: {ConnectionState.ACTIVE, ConnectionState.CLOSING, ConnectionState.CLOSED},
        ConnectionState.ACTIVE: {ConnectionState.CLOSING, ConnectionState.CLOSED, ConnectionState.INITIALIZING},
        ConnectionState.CLOSING: {ConnectionState.CLOSED},
        ConnectionState.CLOSED: set(),  # terminal
    }

    def __init__(self):
        self._state = ConnectionState.CONNECTING
        self._lock = asyncio.Lock()
        self._history: list[tuple[float, ConnectionState]] = [(time.monotonic(), self._state)]
        logger.info("[state] Initial state: %s", self._state.value)

    @property
    def state(self) -> ConnectionState:
        return self._state

    @property
    def is_active(self) -> bool:
        return self._state == ConnectionState.ACTIVE

    @property
    def is_terminal(self) -> bool:
        return self._state == ConnectionState.CLOSED

    async def transition(self, target: ConnectionState) -> bool:
        """Attempt state transition. Returns True if successful."""
        async with self._lock:
            if target == self._state:
                return True
            allowed = self._VALID_TRANSITIONS.get(self._state, set())
            if target not in allowed:
                logger.warning(
                    "[state] Invalid transition %s → %s (allowed: %s)",
                    self._state.value,
                    target.value,
                    [s.value for s in allowed],
                )
                return False
            old = self._state
            self._state = target
            self._history.append((time.monotonic(), target))
            logger.info("[state] %s → %s", old.value, target.value)
            return True


# ---------------------------------------------------------------------------
# Watchdog
# ---------------------------------------------------------------------------
class ModelTurnWatchdog:
    """Detect stuck Gemini sessions: >N consecutive modelTurn events without turnComplete."""

    def __init__(self, threshold: int = _WATCHDOG_MAX_MODEL_TURNS):
        self._consecutive = 0
        self._threshold = threshold
        self._tripped = False

    def on_model_turn(self) -> bool:
        """Record a modelTurn event. Returns True if watchdog has tripped."""
        self._consecutive += 1
        if self._consecutive > self._threshold and not self._tripped:
            self._tripped = True
            logger.error(
                "[watchdog] %d consecutive modelTurn events without turnComplete — force-reset needed",
                self._consecutive,
            )
            return True
        return False

    def on_turn_complete(self):
        """Reset the counter on turnComplete."""
        self._consecutive = 0
        self._tripped = False

    @property
    def tripped(self) -> bool:
        return self._tripped


# ---------------------------------------------------------------------------
# Close code helpers
# ---------------------------------------------------------------------------
_CLOSE_CODE_LABELS = {
    1000: "Normal closure",
    1001: "Going away",
    1006: "Abnormal closure (no close frame)",
    1011: "Internal server error",
}


def _describe_close_code(code: int | None) -> str:
    if code is None:
        return "unknown"
    return _CLOSE_CODE_LABELS.get(code, f"code {code}")


# ---------------------------------------------------------------------------
# Pipeline coroutines
# ---------------------------------------------------------------------------
async def browser_to_gemini(ws: WebSocket, session, state: ConnectionStateMachine) -> None:
    """Forward audio/video chunks from the browser WebSocket to Gemini."""
    try:
        chunk_count = 0
        while not state.is_terminal:
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

                # Decode base64 with error handling
                try:
                    decoded = base64.b64decode(b64data)
                except Exception as exc:
                    logger.warning("Base64 decode failed, skipping chunk: %s", exc)
                    continue

                if mime.startswith("audio/"):
                    # Validate PCM format
                    valid, reason = validate_pcm_format(decoded)
                    if not valid:
                        logger.debug("Invalid PCM data: %s", reason)
                        continue

                    # Compute audio level and send to frontend periodically
                    chunk_count += 1
                    level = compute_audio_level(decoded)

                    if chunk_count % _LEVEL_METER_INTERVAL == 0:
                        try:
                            await ws.send_json({
                                "type": "audioLevel",
                                "rms": level.rms,
                                "peak": level.peak,
                                "db": level.db,
                                "isSpeech": level.is_speech,
                            })
                        except Exception:
                            pass  # Don't crash if level send fails

                    # VAD: skip silence/noise to avoid gibberish transcriptions
                    if not level.is_speech:
                        continue

                    await session.send_realtime_input(
                        audio=gt.Blob(data=decoded, mime_type="audio/pcm")
                    )
                elif mime.startswith("image/"):
                    await session.send_realtime_input(
                        video=gt.Blob(data=decoded, mime_type=mime)
                    )

    except WebSocketDisconnect:
        logger.info("Browser disconnected (browser_to_gemini)")
    except asyncio.CancelledError:
        pass
    except Exception as exc:
        logger.error("browser->gemini error: %s", exc)


async def gemini_to_browser(
    ws: WebSocket,
    session,
    state: ConnectionStateMachine,
    watchdog: ModelTurnWatchdog,
) -> str | None:
    """Forward Gemini model output to the browser WebSocket.

    Returns a reason string if the watchdog trips or an error occurs,
    None on clean exit.
    """
    logger.info("gemini_to_browser started, waiting for Gemini audio...")
    try:
        async for response in session.receive():
            if state.is_terminal:
                break

            logger.debug("gemini response: setup=%s srv=%s", response.setup_complete, bool(response.server_content))
            # Skip setup_complete events
            if response.setup_complete:
                continue

            out: dict = {"serverContent": {}}
            sc = out["serverContent"]
            srv = response.server_content

            audio_data = None
            text_data = None
            has_real_content = False  # True only if non-thought content exists

            if srv and srv.model_turn and srv.model_turn.parts:
                for part in srv.model_turn.parts:
                    if getattr(part, "thought", False):
                        continue  # Skip thinking tokens entirely
                    has_real_content = True
                    if part.inline_data and part.inline_data.data:
                        audio_data = part.inline_data.data
                    if part.text:
                        text_data = part.text

            if audio_data:
                logger.debug('Got audio from Gemini: %d bytes', len(audio_data))
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

            if not audio_data and not text_data and not has_real_content and srv and srv.model_turn:
                logger.debug('Model turn with only thought tokens (filtered)')
            if text_data:
                if "modelTurn" not in sc:
                    sc["modelTurn"] = {"parts": []}
                sc["modelTurn"]["parts"].append({"text": text_data})

            if srv:
                if srv.turn_complete:
                    sc["turnComplete"] = True
                    watchdog.on_turn_complete()
                elif has_real_content:
                    if watchdog.on_model_turn():
                        # Watchdog tripped — notify browser and request reset
                        await _safe_send(ws, {
                            "type": "error",
                            "message": "Session stuck — reconnecting...",
                            "reconnect": True,
                        })
                        return "watchdog_tripped"

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

            if sc:
                await _safe_send(ws, out)

    except asyncio.CancelledError:
        pass
    except Exception as exc:
        logger.error("gemini->browser error: %s", exc)
        return f"gemini_error: {exc}"
    return None


async def keepalive_ping(ws: WebSocket, state: ConnectionStateMachine) -> None:
    """Send periodic keepalive pings. Faster during init, slower when active."""
    try:
        while not state.is_terminal:
            interval = (
                _KEEPALIVE_INTERVAL_INIT
                if state.state in (ConnectionState.CONNECTING, ConnectionState.INITIALIZING)
                else _KEEPALIVE_INTERVAL_ACTIVE
            )
            await asyncio.sleep(interval)
            if state.is_terminal:
                break
            await _safe_send(ws, {"type": "keepalive"})
    except asyncio.CancelledError:
        pass
    except Exception:
        pass  # Connection closed, exit silently


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
async def _safe_send(ws: WebSocket, data: dict) -> bool:
    """Send JSON to WebSocket, swallowing errors if already closed."""
    try:
        if ws.client_state == WebSocketState.CONNECTED:
            await ws.send_json(data)
            return True
    except Exception:
        pass
    return False


async def safe_close(ws: WebSocket, code: int = 1000, reason: str = "") -> None:
    """Close the browser WebSocket with proper code handling."""
    try:
        if ws.client_state == WebSocketState.CONNECTED:
            logger.info(
                "[ws] Closing browser WebSocket: %s (%s)",
                _describe_close_code(code),
                reason or "no reason",
            )
            await ws.close(code=code, reason=reason)
    except Exception:
        pass
