"""OpenAI provider adapters for live conversation and synthesis.

Wraps the ``openai`` SDK. All OpenAI-specific logic is confined here;
the rest of the codebase talks to ``LiveProviderBase`` / ``SynthesisProviderBase``.
"""

from __future__ import annotations

import json
import logging
from typing import Any, AsyncIterator

import httpx
from openai import AsyncOpenAI

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


# ── Live provider ───────────────────────────────────────────────────────


class OpenAIRealtimeProvider(LiveProviderBase):
    """Real-time conversation via OpenAI Realtime API (WebRTC-style).

    Note: The current OpenAI Realtime API uses an SDP-based WebRTC flow
    rather than a simple WebSocket. This adapter captures the config;
    actual SDP negotiation happens at the API route layer since it
    requires direct HTTP exchange with the client's browser.

    The adapter stores the session config so routes can pull it without
    touching SDK internals directly.
    """

    def __init__(self) -> None:
        self._session_id: str = ""
        self._config: LiveSessionConfig | None = None

    async def connect(self, session_id: str, config: LiveSessionConfig) -> None:
        if not settings.openai_api_key:
            raise RuntimeError(
                "COUNSELAI_OPENAI_API_KEY not set — cannot initialise OpenAI provider"
            )
        self._session_id = session_id
        self._config = config
        logger.info("OpenAI Realtime configured: session=%s", session_id)

    def build_rtc_session_payload(self) -> dict[str, Any]:
        """Build the JSON payload for OpenAI's ``/v1/realtime/calls`` endpoint."""
        config = self._config or LiveSessionConfig()
        instructions = config.system_instructions or settings.counsellor_instructions
        full_prompt = instructions + (config.scenario_text or "")
        voice = config.voice or settings.openai_realtime_voice

        return {
            "type": "realtime",
            "model": settings.openai_realtime_model,
            "instructions": full_prompt,
            "audio": {
                "output": {"voice": voice},
                "input": {
                    "transcription": {"model": settings.openai_transcription_model},
                    "turn_detection": {
                        "type": "server_vad",
                        "threshold": 0.5,
                        "silence_duration_ms": 500,
                    },
                },
            },
        }

    async def negotiate_sdp(self, sdp_offer: str) -> tuple[int, str]:
        """Exchange SDP offer with OpenAI and return (status_code, response_body).

        This replaces the inline httpx call that lived in the route handler.
        """
        payload = self.build_rtc_session_payload()
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                settings.openai_realtime_url,
                headers={"Authorization": f"Bearer {settings.openai_api_key}"},
                files=[
                    ("sdp", (None, sdp_offer, "application/sdp")),
                    ("session", (None, json.dumps(payload), "application/json")),
                ],
            )
        if resp.status_code not in (200, 201):
            request_id = resp.headers.get("x-request-id", "")
            logger.error(
                "OpenAI realtime call failed: status=%s request_id=%s body=%s",
                resp.status_code,
                request_id,
                resp.text[:500],
            )
        return resp.status_code, resp.text

    # The remaining methods are no-ops because audio flows over WebRTC,
    # not through our server. They exist to satisfy the interface.

    async def send_audio(self, chunk: bytes, mime_type: str = "audio/pcm") -> None:
        pass  # Audio flows directly browser ↔ OpenAI via WebRTC.

    async def send_video_frame(self, frame: bytes, mime_type: str = "image/jpeg") -> None:
        pass  # Not supported by OpenAI Realtime.

    async def send_end_of_turn(self) -> None:
        pass  # VAD handles turn detection.

    async def receive_events(self) -> AsyncIterator[LiveEvent]:
        # WebRTC events are handled client-side; nothing to yield server-side.
        return
        yield  # noqa: make this a generator

    async def disconnect(self) -> None:
        logger.info("OpenAI Realtime disconnected: session=%s", self._session_id)
        self._config = None

    @property
    def provider_name(self) -> str:
        return "openai-realtime"


# ── Synthesis provider ──────────────────────────────────────────────────


class OpenAISynthesisProvider(SynthesisProviderBase):
    """Structured LLM calls (extraction, profiling) via OpenAI Chat Completions."""

    def __init__(self) -> None:
        self._client: AsyncOpenAI | None = None

    def _ensure_client(self) -> AsyncOpenAI:
        if self._client is None:
            if not settings.openai_api_key:
                raise RuntimeError(
                    "COUNSELAI_OPENAI_API_KEY not set — cannot initialise OpenAI synthesis"
                )
            self._client = AsyncOpenAI(api_key=settings.openai_api_key)
        return self._client

    async def generate(self, request: SynthesisRequest) -> SynthesisResponse:
        client = self._ensure_client()

        messages: list[dict[str, Any]] = []
        if request.system_prompt:
            messages.append({"role": "system", "content": request.system_prompt})

        user_content: list[Any] = []
        if request.user_prompt:
            user_content.append({"type": "text", "text": request.user_prompt})
        if request.media_bytes and request.media_mime_type:
            import base64

            b64 = base64.b64encode(request.media_bytes).decode()
            user_content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{request.media_mime_type};base64,{b64}"},
                }
            )
        if user_content:
            messages.append({"role": "user", "content": user_content})

        kwargs: dict[str, Any] = {
            "model": settings.openai_synthesis_model,
            "messages": messages,
            "temperature": request.temperature or settings.openai_synthesis_temperature,
            "max_tokens": request.max_tokens or settings.openai_synthesis_max_tokens,
        }

        if request.json_schema:
            kwargs["response_format"] = {"type": "json_object"}

        completion = await client.chat.completions.create(**kwargs)
        choice = completion.choices[0]
        text = (choice.message.content or "").strip()

        usage: dict[str, int] = {}
        if completion.usage:
            usage = {
                "prompt_tokens": completion.usage.prompt_tokens or 0,
                "completion_tokens": completion.usage.completion_tokens or 0,
                "total_tokens": completion.usage.total_tokens or 0,
            }

        return SynthesisResponse(
            text=text,
            usage=usage,
            model=settings.openai_synthesis_model,
            raw=completion,
        )

    async def transcribe_audio(self, audio: bytes, mime_type: str = "audio/wav") -> str:
        client = self._ensure_client()
        # Use Whisper for transcription via the OpenAI API.
        import tempfile, os

        suffix = ".wav" if "wav" in mime_type else ".webm"
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        try:
            tmp.write(audio)
            tmp.close()
            with open(tmp.name, "rb") as f:
                transcript = await client.audio.transcriptions.create(
                    model="whisper-1",
                    file=f,
                )
            return (transcript.text or "").strip()
        finally:
            os.unlink(tmp.name)

    @property
    def provider_name(self) -> str:
        return "openai"
