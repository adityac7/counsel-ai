"""Minimal WebSocket proxy: Browser ↔ Gemini Live.

No watchdog. No state machine. No reconnection logic.
Just forward audio/video between browser and Gemini.
Let Gemini handle silence, turns, and conversation flow.
"""

import asyncio
import base64
import collections
import json
import logging
import re
import struct
import math
import time
from dataclasses import dataclass, field

from starlette.websockets import WebSocket, WebSocketDisconnect
from google.genai import types as gt

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Devanagari → Roman fallback (safety net if ASR still sends Devanagari)
# ---------------------------------------------------------------------------
_DEVANAGARI_MAP = {
    "अ": "a", "आ": "aa", "इ": "i", "ई": "ee", "उ": "u", "ऊ": "oo",
    "ए": "e", "ऐ": "ai", "ओ": "o", "औ": "au",
    "क": "ka", "ख": "kha", "ग": "ga", "घ": "gha", "ङ": "nga",
    "च": "cha", "छ": "chha", "ज": "ja", "झ": "jha", "ञ": "nya",
    "ट": "ta", "ठ": "tha", "ड": "da", "ढ": "dha", "ण": "na",
    "त": "ta", "थ": "tha", "द": "da", "ध": "dha", "न": "na",
    "प": "pa", "फ": "pha", "ब": "ba", "भ": "bha", "म": "ma",
    "य": "ya", "र": "ra", "ल": "la", "व": "va", "श": "sha",
    "ष": "sha", "स": "sa", "ह": "ha",
    "ा": "aa", "ि": "i", "ी": "ee", "ु": "u", "ू": "oo",
    "े": "e", "ै": "ai", "ो": "o", "ौ": "au",
    "ं": "n", "ः": "h", "ँ": "n",
    "्": "", "़": "",
    "।": ".", "॥": ".",
    "क़": "qa", "ख़": "kha", "ग़": "ga", "ज़": "za", "फ़": "fa",
    "ड़": "da", "ढ़": "dha",
}

_DEVANAGARI_RE = re.compile(r"[\u0900-\u097F]")


def _to_roman(text: str) -> str:
    """Strip any Devanagari that slips through the ASR languageCodes config.

    Primary fix is in gemini_client.py: AudioTranscriptionConfig(languageCodes=["hi-Latn"])
    This is just a safety net fallback.
    """
    if not text or not _DEVANAGARI_RE.search(text):
        return text
    result = text
    for dev, roman in sorted(_DEVANAGARI_MAP.items(), key=lambda x: -len(x[0])):
        result = result.replace(dev, roman)
    result = _DEVANAGARI_RE.sub("", result)
    return result.strip()


def _now_ms() -> int:
    """Current time in milliseconds (monotonic-ish wall clock for turn timing)."""
    return int(time.time() * 1000)


@dataclass
class TranscriptCollector:
    """Accumulates transcription chunks into complete turns."""
    turns: collections.deque = field(default_factory=lambda: collections.deque(maxlen=5000))
    observations: collections.deque = field(default_factory=lambda: collections.deque(maxlen=1000))
    segments: collections.deque = field(default_factory=lambda: collections.deque(maxlen=1000))
    _current_student: str = ""
    _current_counsellor: str = ""
    _turn_counter: int = 0
    _turn_start_ms: int = 0
    _session_origin_ms: int = field(default_factory=_now_ms)

    def _relative_ms(self) -> int:
        """Milliseconds elapsed since the collector was created."""
        return _now_ms() - self._session_origin_ms

    def add_student(self, text: str) -> None:
        # Flush counsellor if switching roles
        if self._current_counsellor:
            self.turns.append({
                "role": "counsellor",
                "text": self._current_counsellor.strip(),
                "start_ms": self._turn_start_ms,
                "end_ms": self._relative_ms(),
            })
            self._current_counsellor = ""
        if not self._current_student:
            self._turn_start_ms = self._relative_ms()
        self._current_student += (" " if self._current_student else "") + text

    def add_counsellor(self, text: str) -> None:
        # Flush student if switching roles
        if self._current_student:
            self.turns.append({
                "role": "student",
                "text": self._current_student.strip(),
                "start_ms": self._turn_start_ms,
                "end_ms": self._relative_ms(),
            })
            self._current_student = ""
        if not self._current_counsellor:
            self._turn_start_ms = self._relative_ms()
        self._current_counsellor += (" " if self._current_counsellor else "") + text

    def flush(self) -> None:
        """Flush any remaining partial turn."""
        now = self._relative_ms()
        if self._current_student:
            self.turns.append({
                "role": "student",
                "text": self._current_student.strip(),
                "start_ms": self._turn_start_ms,
                "end_ms": now,
            })
            self._current_student = ""
        if self._current_counsellor:
            self.turns.append({
                "role": "counsellor",
                "text": self._current_counsellor.strip(),
                "start_ms": self._turn_start_ms,
                "end_ms": now,
            })
            self._current_counsellor = ""

    def on_turn_complete(self) -> None:
        """Called when Gemini signals turnComplete — flush counsellor turn."""
        self._turn_counter += 1
        if self._current_counsellor:
            self.turns.append({
                "role": "counsellor",
                "text": self._current_counsellor.strip(),
                "start_ms": self._turn_start_ms,
                "end_ms": self._relative_ms(),
            })
            self._current_counsellor = ""

    def add_observation(self, observation: dict) -> None:
        """Store a real-time observation from Gemini function calling."""
        observation["timestamp"] = time.time()
        observation["turn_number"] = self._turn_counter
        self.observations.append(observation)

    def add_segment(self, segment: dict) -> None:
        """Store a segment transition from Gemini function calling."""
        segment["timestamp"] = time.time()
        segment["turn_number"] = self._turn_counter
        self.segments.append(segment)


async def browser_to_gemini(ws: WebSocket, session, transcript: TranscriptCollector | None = None) -> str | None:
    """Forward audio/video from browser WebSocket to Gemini Live session.

    This is the ONLY authority on session lifetime. When the browser
    disconnects, the session ends. Period.

    Returns "end_session" if the browser sent an explicit end_session message,
    None otherwise.
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

            # Graceful end-session request from browser
            if msg.get("type") == "end_session":
                logger.info("Browser requested end_session")
                if transcript:
                    transcript.flush()
                return "end_session"

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
                    # Forward all audio to Gemini — it has its own VAD.
                    # Server-side gating causes Gemini to close the session.
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


async def gemini_to_browser(ws: WebSocket, session, resumption_state: dict | None = None, transcript: TranscriptCollector | None = None) -> None:
    """Forward Gemini responses to browser WebSocket.

    Key pattern from official docs: wrap session.receive() in while True.
    Each receive() call yields one conversational turn. When the turn
    completes (turnComplete), we loop back for the next turn.
    The session stays alive across turns.

    Also captures session_resumption_update handles for reconnection.
    """
    if resumption_state is None:
        resumption_state = {}

    try:
        while True:
            try:
                # Each receive() gives us one turn
                async for response in session.receive():
                    # Skip setup events
                    if response.setup_complete:
                        continue

                    # Capture resumption handle for reconnection
                    if response.session_resumption_update:
                        update = response.session_resumption_update
                        if getattr(update, "resumable", False) and getattr(update, "new_handle", None):
                            resumption_state["handle"] = update.new_handle
                            logger.debug("Resumption handle updated")

                    # Handle GoAway — Gemini tells us to reconnect
                    if response.go_away:
                        logger.info("Received GoAway from Gemini — connection will be recycled")
                        try:
                            await ws.send_json({"type": "go_away"})
                        except Exception:
                            pass
                        # Signal to the caller that we need to reconnect
                        resumption_state["go_away"] = True
                        return  # Exit so caller can reconnect

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
                        if transcript:
                            transcript.on_turn_complete()

                    # Transcriptions
                    if srv.input_transcription:
                        t = getattr(srv.input_transcription, "text", "")
                        if t and t.strip():
                            t = _to_roman(t.strip())
                            sc["inputTranscription"] = {"text": t}
                            if transcript:
                                transcript.add_student(t)

                    if srv.output_transcription:
                        t = getattr(srv.output_transcription, "text", "")
                        if t and t.strip():
                            t = _to_roman(t.strip())
                            sc["outputTranscription"] = {"text": t}
                            if transcript:
                                transcript.add_counsellor(t)

                    # Send to browser if we have content
                    if sc:
                        try:
                            await ws.send_json(out)
                        except Exception:
                            return  # Browser gone

                # receive() iterator ended — this is normal between turns.
                # Wait briefly then loop back to receive the next turn.
                logger.debug("Turn completed, waiting for next turn...")
                await asyncio.sleep(0.1)

            except asyncio.CancelledError:
                raise  # Propagate cancellation — session is ending
            except Exception as inner_exc:
                # Gemini receive raised (e.g., connection hiccup).
                # Do NOT exit — wait and retry. Only GoAway or cancellation
                # should end this loop. Browser disconnect is handled by
                # browser_to_gemini exiting, which cancels us.
                logger.warning("gemini→browser receive error (retrying): %s", inner_exc)
                await asyncio.sleep(0.5)

    except asyncio.CancelledError:
        pass
    except Exception as exc:
        logger.error("gemini→browser fatal error: %s", exc)
    finally:
        if transcript:
            transcript.flush()


async def session_timer(
    ws: WebSocket,
    session,
    transcript: TranscriptCollector,
    max_sec: int = 420,
    wrapup_sec: int = 90,
) -> None:
    """Enforce session time limit with AI-guided wrap-up.

    At max_sec - wrapup_sec: inject wrapup prompt to Gemini + warn browser.
    At max_sec: send timeout to browser and return.
    """
    wrapup_at = max_sec - wrapup_sec
    try:
        await asyncio.sleep(wrapup_at)
        # Tell Gemini to wrap up naturally
        try:
            await session.send_client_content(
                turns=gt.Content(parts=[gt.Part(
                    text=(
                        "TIME CHECK: The session is ending in about 1 minute. "
                        "This is your signal to wrap up. Start closing naturally — "
                        "briefly acknowledge what you discussed (2-3 sentences, not a full summary), "
                        "thank the student warmly, and say goodbye. "
                        "End with something like: 'Accha beta, bahut acchi baat ki tumne aaj. Take care.'"
                    )
                )]),
                turn_complete=True,
            )
        except Exception as exc:
            logger.warning("Failed to send wrapup prompt: %s", exc)
        # Warn browser
        try:
            await ws.send_json({
                "type": "wrapup_warning",
                "remaining_seconds": wrapup_sec,
            })
        except Exception:
            pass
        logger.info("Wrapup warning sent (%ds remaining)", wrapup_sec)

        # Wait for remaining time
        await asyncio.sleep(wrapup_sec)
        # Session timeout
        try:
            await ws.send_json({"type": "session_timeout"})
        except Exception:
            pass
        logger.info("Session timed out after %ds", max_sec)
    except asyncio.CancelledError:
        pass
    finally:
        transcript.flush()


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
