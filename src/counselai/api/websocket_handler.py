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
import time
from dataclasses import dataclass, field

from starlette.websockets import WebSocket, WebSocketDisconnect
from google.genai import types as gt

from counselai.api.audio_utils import compute_audio_level

logger = logging.getLogger(__name__)


def _now_ms() -> int:
    """Current time in milliseconds (monotonic-ish wall clock for turn timing)."""
    return int(time.time() * 1000)


def _normalize_transcript(text: str) -> str:
    """Collapse all whitespace runs to single spaces.

    Why: Gemini streams transcript text in chunks that may contain stray
    newlines or double spaces. The live summary uses ``white-space: pre-wrap``
    while the dashboard uses default ``white-space: normal``, so unnormalized
    text renders inconsistently across the two views.
    """
    return " ".join(text.split())


@dataclass
class UsageAccumulator:
    """Accumulates Gemini Live ``usage_metadata`` across turns.

    Gemini Live emits a ``usage_metadata`` payload per response. Fields may
    be ``None`` or missing; we treat those as 0 and keep a running total so
    the route handler can persist one row at session end.
    """
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    total_tokens: int = 0
    input_modality: dict = field(default_factory=dict)
    output_modality: dict = field(default_factory=dict)

    def add(self, meta) -> None:
        if meta is None:
            return
        self.input_tokens += int(getattr(meta, "prompt_token_count", 0) or 0)
        self.output_tokens += int(getattr(meta, "response_token_count", 0) or 0)
        self.cached_tokens += int(getattr(meta, "cached_content_token_count", 0) or 0)
        self.total_tokens += int(getattr(meta, "total_token_count", 0) or 0)
        for item in getattr(meta, "prompt_tokens_details", None) or []:
            k = str(getattr(item, "modality", "")).upper()
            if k:
                self.input_modality[k] = self.input_modality.get(k, 0) + int(getattr(item, "token_count", 0) or 0)
        for item in getattr(meta, "response_tokens_details", None) or []:
            k = str(getattr(item, "modality", "")).upper()
            if k:
                self.output_modality[k] = self.output_modality.get(k, 0) + int(getattr(item, "token_count", 0) or 0)


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
                "text": _normalize_transcript(self._current_counsellor),
                "start_ms": self._turn_start_ms,
                "end_ms": self._relative_ms(),
            })
            self._current_counsellor = ""
        if not self._current_student:
            self._turn_start_ms = self._relative_ms()
        # Concat raw — Gemini chunks carry their own spacing.
        self._current_student += text

    def add_counsellor(self, text: str) -> None:
        # Flush student if switching roles
        if self._current_student:
            self.turns.append({
                "role": "student",
                "text": _normalize_transcript(self._current_student),
                "start_ms": self._turn_start_ms,
                "end_ms": self._relative_ms(),
            })
            self._current_student = ""
        if not self._current_counsellor:
            self._turn_start_ms = self._relative_ms()
        # Concat raw — Gemini chunks carry their own spacing.
        self._current_counsellor += text

    def flush(self) -> None:
        """Flush any remaining partial turn."""
        now = self._relative_ms()
        if self._current_student:
            self.turns.append({
                "role": "student",
                "text": _normalize_transcript(self._current_student),
                "start_ms": self._turn_start_ms,
                "end_ms": now,
            })
            self._current_student = ""
        if self._current_counsellor:
            self.turns.append({
                "role": "counsellor",
                "text": _normalize_transcript(self._current_counsellor),
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
                "text": _normalize_transcript(self._current_counsellor),
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
                    # MUST include sample rate in mime type, otherwise Gemini
                    # misinterprets the PCM stream and transcription goes bad.
                    # Browser captures at 16kHz (see session.js geminiAudioCtx).
                    await session.send_realtime_input(
                        audio=gt.Blob(data=decoded, mime_type="audio/pcm;rate=16000")
                    )

                    # Send audio level to frontend periodically
                    chunk_count += 1
                    if chunk_count % 5 == 0:
                        level = compute_audio_level(decoded)
                        try:
                            await ws.send_json({
                                "type": "audioLevel",
                                "rms": round(level.rms * 32768),
                                "peak": max(1, round(level.peak * 32768)),
                                "db": level.db,
                                "isSpeech": level.is_speech,
                            })
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
        exc_str = str(exc)
        # 1011 = Gemini internal error — transient, worth retrying at caller level
        if "1011" in exc_str or "internal error" in exc_str.lower():
            logger.warning("⏱ browser→gemini transient error (signalling retry): %s", exc)
            return "transient_error"
        logger.error("browser→gemini fatal error: %s", exc)


async def gemini_to_browser(
    ws: WebSocket,
    session,
    resumption_state: dict | None = None,
    transcript: TranscriptCollector | None = None,
    language: str = "hinglish",
    usage_agg: UsageAccumulator | None = None,
) -> None:
    """Forward Gemini responses to browser WebSocket."""
    if resumption_state is None:
        resumption_state = {}

    # One-per-turn latch: emit ai_speaking=true the first time a turn
    # carries model audio, ai_speaking=false when turn_complete arrives.
    speaking_flag = False

    # Per-turn latency tracking
    _t_input_transcription: float | None = None  # when student speech ended (VAD fired)
    _t_first_audio: float | None = None           # when first AI audio chunk arrived
    _t_turn_start: float | None = None            # when first model content packet arrived
    _had_output_transcription: bool = False       # whether AI produced any transcript this turn
    _turn_index: int = 0

    try:
        while True:
            try:
                # Each receive() gives us one turn
                async for response in session.receive():
                    # Accumulate token usage (fields may be missing/None).
                    if usage_agg is not None:
                        try:
                            usage_agg.add(getattr(response, "usage_metadata", None))
                        except Exception as exc:
                            logger.debug("usage_metadata capture skipped: %s", exc)

                    # Skip setup events
                    if response.setup_complete:
                        logger.info("⏱ [turn=%d] setup_complete received", _turn_index)
                        continue

                    # Capture resumption handle for reconnection
                    if response.session_resumption_update:
                        update = response.session_resumption_update
                        if getattr(update, "resumable", False) and getattr(update, "new_handle", None):
                            resumption_state["handle"] = update.new_handle
                            logger.debug("Resumption handle updated")

                    # Handle GoAway — Gemini tells us to reconnect
                    if response.go_away:
                        logger.info("⏱ [turn=%d] GoAway received — recycling connection", _turn_index)
                        try:
                            await ws.send_json({"type": "go_away"})
                        except Exception:
                            pass
                        resumption_state["go_away"] = True
                        return

                    srv = response.server_content
                    # Only start the turn timer once we have actual model content
                    if srv and _t_turn_start is None:
                        _t_turn_start = time.monotonic()
                    if not srv:
                        continue

                    out = {"serverContent": {}}
                    sc = out["serverContent"]

                    # Model audio/text output
                    has_inline_audio = False
                    if srv.model_turn and srv.model_turn.parts:
                        parts_out = []
                        for part in srv.model_turn.parts:
                            # Skip thinking tokens
                            if getattr(part, "thought", False):
                                continue
                            if part.inline_data and part.inline_data.data:
                                has_inline_audio = True
                                # Log first audio chunk latency
                                if _t_first_audio is None:
                                    _t_first_audio = time.monotonic()
                                    if _t_input_transcription is not None:
                                        vad_to_audio_ms = (_t_first_audio - _t_input_transcription) * 1000
                                        logger.info(
                                            "⏱ [turn=%d] VAD→first-audio: %.0fms",
                                            _turn_index, vad_to_audio_ms,
                                        )
                                    else:
                                        logger.info(
                                            "⏱ [turn=%d] first-audio at +%.0fms (no VAD ref)",
                                            _turn_index,
                                            (_t_first_audio - (_t_turn_start or _t_first_audio)) * 1000,
                                        )
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

                    # Emit ai_speaking=true exactly once per turn, the first
                    # time the model sends inline audio.
                    if has_inline_audio and not speaking_flag:
                        speaking_flag = True
                        try:
                            await ws.send_json({"type": "ai_speaking", "state": True})
                        except Exception:
                            return

                    # Turn complete
                    if srv.turn_complete:
                        sc["turnComplete"] = True
                        if transcript:
                            transcript.on_turn_complete()
                        if speaking_flag:
                            speaking_flag = False
                            try:
                                await ws.send_json({"type": "ai_speaking", "state": False})
                            except Exception:
                                return
                        # Log turn outcome
                        _elapsed = (time.monotonic() - _t_turn_start) * 1000 if _t_turn_start else 0
                        if _t_first_audio is not None:
                            stream_ms = (time.monotonic() - _t_first_audio) * 1000
                            logger.info("⏱ [turn=%d] AI streaming duration: %.0fms", _turn_index, stream_ms)
                        elif _had_output_transcription:
                            # AI produced transcript but no audio (text-only response)
                            logger.info("⏱ [turn=%d] AI text-only response at +%.0fms", _turn_index, _elapsed)
                        elif _t_turn_start is not None:
                            # No audio, no transcript — likely student input turn boundary
                            # (Gemini signals student turn end before AI starts responding)
                            logger.info(
                                "⏱ [turn=%d] input-turn-boundary at +%.0fms "
                                "(student turn end — AI response follows)",
                                _turn_index, _elapsed,
                            )
                        # Reset per-turn state
                        _turn_index += 1
                        _t_input_transcription = None
                        _t_first_audio = None
                        _t_turn_start = None
                        _had_output_transcription = False

                    # Transcriptions — pass through raw text from Gemini.
                    if srv.input_transcription:
                        t = getattr(srv.input_transcription, "text", "")
                        if t and t.strip():
                            # Each new inputTranscription chunk = VAD is active.
                            # Last chunk before modelTurn = student finished speaking.
                            _t_input_transcription = time.monotonic()
                            sc["inputTranscription"] = {"text": t}
                            if transcript:
                                transcript.add_student(t)

                    if srv.output_transcription:
                        t = getattr(srv.output_transcription, "text", "")
                        if t and t.strip():
                            _had_output_transcription = True
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
                logger.debug("⏱ [turn=%d] receive() exhausted — looping", _turn_index)
                await asyncio.sleep(0)

            except asyncio.CancelledError:
                raise
            except Exception as inner_exc:
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
    max_sec: int = 300,
    wrapup_sec: int = 90,
    language: str = "hinglish",
) -> None:
    """Enforce session time limit with AI-guided wrap-up.

    At max_sec - wrapup_sec: inject wrapup prompt to Gemini + warn browser.
    At max_sec: send timeout to browser and return.
    """
    from counselai.api.constants import WRAPUP_PROMPTS

    wrapup_at = max_sec - wrapup_sec
    try:
        await asyncio.sleep(wrapup_at)
        # Tell Gemini to wrap up naturally
        try:
            prompt = WRAPUP_PROMPTS.get(language, WRAPUP_PROMPTS["hinglish"])
            remaining_min = max(1, wrapup_sec // 60)
            await session.send_client_content(
                turns=gt.Content(parts=[gt.Part(
                    text=prompt.format(minutes=remaining_min),
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


