"""Gemini provider adapters for live conversation and synthesis.

Wraps the ``google.genai`` SDK. All Gemini-specific logic is confined here;
the rest of the codebase talks to ``LiveProviderBase`` / ``SynthesisProviderBase``.
"""

from __future__ import annotations

import base64
import logging
import struct
from typing import AsyncIterator

from google import genai
from google.genai import types as gt

from counselai.live.providers.base import (
    AudioChunkEvent,
    LiveEvent,
    LiveProviderBase,
    LiveSessionConfig,
    SetupCompleteEvent,
    SynthesisProviderBase,
    SynthesisRequest,
    SynthesisResponse,
    TranscriptEvent,
    TurnCompleteEvent,
    Speaker,
)
from counselai.settings import settings

logger = logging.getLogger(__name__)


# ── Helpers ─────────────────────────────────────────────────────────────


def _build_client() -> genai.Client:
    """Create a Gemini client from settings."""
    if not settings.gemini_api_key:
        raise RuntimeError(
            "COUNSELAI_GEMINI_API_KEY not set — cannot initialise Gemini provider"
        )
    return genai.Client(
        api_key=settings.gemini_api_key,
        http_options={"api_version": settings.gemini_api_version},
    )


def _silent_trigger_audio(sample_rate: int = 24000, duration_ms: int = 100) -> bytes:
    """Generate a short silent PCM16 blob to trigger the model's first turn."""
    num_samples = int(sample_rate * duration_ms / 1000)
    return struct.pack("<" + "h" * num_samples, *([0] * num_samples))


# ── Live provider ───────────────────────────────────────────────────────


class GeminiLiveProvider(LiveProviderBase):
    """Bidirectional audio conversation via Gemini Live API."""

    def __init__(self) -> None:
        self._client: genai.Client | None = None
        self._session: object | None = None  # genai AsyncLiveSession
        self._session_ctx: object | None = None
        self._session_id: str = ""

    # -- lifecycle --------------------------------------------------------

    async def connect(self, session_id: str, config: LiveSessionConfig) -> None:
        self._client = _build_client()
        self._session_id = session_id

        voice = config.voice or settings.gemini_live_voice
        live_config = gt.LiveConnectConfig(
            response_modalities=["AUDIO"],
            speech_config=gt.SpeechConfig(
                voice_config=gt.VoiceConfig(
                    prebuilt_voice_config=gt.PrebuiltVoiceConfig(voice_name=voice)
                )
            ),
        )

        # Open the streaming connection.
        self._session_ctx = self._client.aio.live.connect(
            model=settings.gemini_live_model,
            config=live_config,
        )
        self._session = await self._session_ctx.__aenter__()
        logger.info(
            "Gemini Live connected: session=%s model=%s",
            session_id,
            settings.gemini_live_model,
        )

        # Inject system instructions + scenario as client context.
        instructions = config.system_instructions or settings.counsellor_instructions
        full_prompt = instructions + (config.scenario_text or "")
        await self._session.send_client_content(
            turns=gt.Content(parts=[gt.Part(text=full_prompt)]),
            turn_complete=False,
        )

        # Send silent audio to elicit the model's greeting.
        trigger = _silent_trigger_audio(settings.audio_sample_rate)
        await self._session.send_realtime_input(
            audio=gt.Blob(data=trigger, mime_type="audio/pcm")
        )
        await self._session.send_realtime_input(audio_stream_end=True)

    async def send_audio(self, chunk: bytes, mime_type: str = "audio/pcm") -> None:
        if self._session is None:
            raise RuntimeError("Not connected")
        await self._session.send_realtime_input(
            audio=gt.Blob(data=chunk, mime_type=mime_type)
        )

    async def send_video_frame(self, frame: bytes, mime_type: str = "image/jpeg") -> None:
        if self._session is None:
            raise RuntimeError("Not connected")
        await self._session.send_realtime_input(
            video=gt.Blob(data=frame, mime_type=mime_type)
        )

    async def send_end_of_turn(self) -> None:
        if self._session is None:
            raise RuntimeError("Not connected")
        await self._session.send_realtime_input(audio_stream_end=True)

    async def receive_events(self) -> AsyncIterator[LiveEvent]:
        if self._session is None:
            raise RuntimeError("Not connected")

        async for response in self._session.receive():
            # Setup complete — skip, we already signalled externally
            if response.setup_complete:
                yield SetupCompleteEvent()
                continue

            srv = response.server_content
            if not srv:
                continue

            # Model turn audio + text parts
            if srv.model_turn and srv.model_turn.parts:
                for part in srv.model_turn.parts:
                    if part.inline_data and part.inline_data.data:
                        yield AudioChunkEvent(
                            data=part.inline_data.data,
                            mime_type=part.inline_data.mime_type or "audio/pcm",
                        )
                    if part.text:
                        yield TranscriptEvent(
                            speaker=Speaker.COUNSELLOR,
                            text=part.text,
                        )

            # Transcriptions
            if srv.input_transcription:
                text = getattr(srv.input_transcription, "text", "")
                if text and text.strip():
                    yield TranscriptEvent(
                        speaker=Speaker.STUDENT,
                        text=text.strip(),
                    )

            if srv.output_transcription:
                text = getattr(srv.output_transcription, "text", "")
                if text and text.strip():
                    yield TranscriptEvent(
                        speaker=Speaker.COUNSELLOR,
                        text=text.strip(),
                    )

            if srv.turn_complete:
                yield TurnCompleteEvent()

    async def disconnect(self) -> None:
        if self._session_ctx is not None:
            try:
                await self._session_ctx.__aexit__(None, None, None)
            except Exception:
                logger.debug("Gemini session cleanup error (ignored)", exc_info=True)
            self._session = None
            self._session_ctx = None
        logger.info("Gemini Live disconnected: session=%s", self._session_id)

    @property
    def provider_name(self) -> str:
        return "gemini-live"


# ── Synthesis provider ──────────────────────────────────────────────────

# Phrases that indicate no meaningful speech was detected.
_SILENCE_INDICATORS = frozenset(
    ["silence", "no speech", "no clear speech", "no audio", "no words", "empty"]
)


class GeminiSynthesisProvider(SynthesisProviderBase):
    """Structured LLM calls (extraction, profiling, transcription) via Gemini."""

    def __init__(self) -> None:
        self._client: genai.Client | None = None

    def _ensure_client(self) -> genai.Client:
        if self._client is None:
            self._client = _build_client()
        return self._client

    async def generate(self, request: SynthesisRequest) -> SynthesisResponse:
        client = self._ensure_client()

        contents: list = []
        if request.system_prompt:
            contents.append(request.system_prompt)
        if request.user_prompt:
            contents.append(request.user_prompt)
        if request.media_bytes and request.media_mime_type:
            contents.append(
                gt.Part.from_bytes(data=request.media_bytes, mime_type=request.media_mime_type)
            )

        config = gt.GenerateContentConfig(
            temperature=request.temperature or settings.gemini_synthesis_temperature,
            max_output_tokens=request.max_tokens or settings.gemini_synthesis_max_tokens,
        )

        response = client.models.generate_content(
            model=settings.gemini_synthesis_model,
            contents=contents,
            config=config,
        )

        text = (response.text or "").strip()
        usage: dict[str, int] = {}
        if hasattr(response, "usage_metadata") and response.usage_metadata:
            um = response.usage_metadata
            usage = {
                "prompt_tokens": getattr(um, "prompt_token_count", 0) or 0,
                "completion_tokens": getattr(um, "candidates_token_count", 0) or 0,
                "total_tokens": getattr(um, "total_token_count", 0) or 0,
            }

        return SynthesisResponse(
            text=text,
            usage=usage,
            model=settings.gemini_synthesis_model,
            raw=response,
        )

    async def transcribe_audio(self, audio: bytes, mime_type: str = "audio/wav") -> str:
        client = self._ensure_client()

        prompt = (
            "Transcribe the human speech in this audio to text. Return ONLY the exact "
            "spoken words in the original language (Hindi/Hinglish/English). If there is "
            "no clear speech, return an empty string. Do NOT describe sounds or noises."
        )
        response = client.models.generate_content(
            model=settings.gemini_synthesis_model,
            contents=[
                prompt,
                gt.Part.from_bytes(data=audio, mime_type=mime_type),
            ],
            config=gt.GenerateContentConfig(),
        )

        text = (response.text or "").strip()
        # Filter out model responses that describe silence rather than transcribing.
        if any(s in text.lower() for s in _SILENCE_INDICATORS) and len(text) < 50:
            return ""
        return text

    @property
    def provider_name(self) -> str:
        return "gemini"
