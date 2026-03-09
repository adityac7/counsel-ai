"""Abstract base classes for provider adapters.

Two distinct adapter families:
- ``LiveProviderBase``: real-time bidirectional audio/text conversation.
- ``SynthesisProviderBase``: post-session structured LLM calls (extraction, profiling).

Domain code depends on these interfaces, never on SDK imports directly.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncIterator


# ── Shared types ────────────────────────────────────────────────────────


class Speaker(str, Enum):
    STUDENT = "student"
    COUNSELLOR = "counsellor"
    SYSTEM = "system"


@dataclass
class TranscriptEvent:
    """A single transcript fragment emitted during a live session."""

    speaker: Speaker
    text: str
    start_ms: int | None = None
    end_ms: int | None = None


@dataclass
class AudioChunkEvent:
    """A chunk of audio returned by the model for playback."""

    data: bytes
    mime_type: str = "audio/pcm"


@dataclass
class TurnCompleteEvent:
    """Signals the model finished its turn."""

    pass


@dataclass
class SetupCompleteEvent:
    """Signals the provider session is ready."""

    pass


# Union of all possible outbound events from a live provider.
LiveEvent = TranscriptEvent | AudioChunkEvent | TurnCompleteEvent | SetupCompleteEvent


@dataclass
class LiveSessionConfig:
    """Configuration passed when opening a live provider session."""

    system_instructions: str = ""
    scenario_text: str = ""
    student_name: str = "Student"
    voice: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


# ── Live provider ───────────────────────────────────────────────────────


class LiveProviderBase(ABC):
    """Interface for real-time bidirectional conversation providers.

    Lifecycle: ``connect()`` → send/receive loop → ``disconnect()``.
    """

    @abstractmethod
    async def connect(self, session_id: str, config: LiveSessionConfig) -> None:
        """Open a live session with the provider."""
        ...

    @abstractmethod
    async def send_audio(self, chunk: bytes, mime_type: str = "audio/pcm") -> None:
        """Stream a chunk of audio from the student's microphone."""
        ...

    @abstractmethod
    async def send_video_frame(self, frame: bytes, mime_type: str = "image/jpeg") -> None:
        """Send a video frame (for multimodal providers)."""
        ...

    @abstractmethod
    async def send_end_of_turn(self) -> None:
        """Signal that the student has stopped speaking."""
        ...

    @abstractmethod
    async def receive_events(self) -> AsyncIterator[LiveEvent]:
        """Yield events from the provider (audio, transcript, turn-complete)."""
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        """Tear down the session."""
        ...

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Human-readable identifier, e.g. 'gemini-live'."""
        ...


# ── Synthesis provider ──────────────────────────────────────────────────


@dataclass
class SynthesisRequest:
    """A single structured LLM call for post-session analysis."""

    system_prompt: str = ""
    user_prompt: str = ""
    json_schema: dict[str, Any] | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    # For multimodal calls (e.g. transcribe audio)
    media_bytes: bytes | None = None
    media_mime_type: str | None = None


@dataclass
class SynthesisResponse:
    """Structured response from a synthesis LLM call."""

    text: str
    usage: dict[str, int] = field(default_factory=dict)
    model: str = ""
    raw: Any = None  # provider-specific raw response


class SynthesisProviderBase(ABC):
    """Interface for structured LLM calls (extraction, profiling, transcription).

    Unlike live providers, these are stateless request/response pairs.
    """

    @abstractmethod
    async def generate(self, request: SynthesisRequest) -> SynthesisResponse:
        """Run a single structured generation request."""
        ...

    @abstractmethod
    async def transcribe_audio(self, audio: bytes, mime_type: str = "audio/wav") -> str:
        """Transcribe audio to text. Returns empty string on silence."""
        ...

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Human-readable identifier, e.g. 'gemini'."""
        ...
