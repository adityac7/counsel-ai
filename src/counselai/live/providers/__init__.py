"""Provider factory — single entry point for getting adapters by name.

Usage:
    from counselai.live.providers import get_live_provider, get_synthesis_provider

    live = get_live_provider("gemini-live")
    synth = get_synthesis_provider("gemini")
"""

from __future__ import annotations

from counselai.live.providers.base import (
    LiveProviderBase,
    SynthesisProviderBase,
    LiveSessionConfig,
    LiveEvent,
    TranscriptEvent,
    AudioChunkEvent,
    TurnCompleteEvent,
    SetupCompleteEvent,
    SynthesisRequest,
    SynthesisResponse,
    Speaker,
)
from counselai.settings import settings


def get_live_provider(name: str | None = None) -> LiveProviderBase:
    """Return a live conversation provider instance by name.

    Falls back to ``settings.default_live_provider`` when *name* is ``None``.
    """
    provider_name = name or settings.default_live_provider

    if provider_name == "gemini-live":
        from counselai.live.providers.gemini import GeminiLiveProvider

        return GeminiLiveProvider()

    if provider_name == "openai-realtime":
        from counselai.live.providers.openai import OpenAIRealtimeProvider

        return OpenAIRealtimeProvider()

    raise ValueError(f"Unknown live provider: {provider_name!r}")


def get_synthesis_provider(name: str | None = None) -> SynthesisProviderBase:
    """Return a synthesis/analysis provider instance by name.

    Falls back to ``settings.default_synthesis_provider`` when *name* is ``None``.
    """
    provider_name = name or settings.default_synthesis_provider

    if provider_name == "gemini":
        from counselai.live.providers.gemini import GeminiSynthesisProvider

        return GeminiSynthesisProvider()

    if provider_name == "openai":
        from counselai.live.providers.openai import OpenAISynthesisProvider

        return OpenAISynthesisProvider()

    raise ValueError(f"Unknown synthesis provider: {provider_name!r}")


__all__ = [
    # Factories
    "get_live_provider",
    "get_synthesis_provider",
    # Base classes
    "LiveProviderBase",
    "SynthesisProviderBase",
    # Config / event types
    "LiveSessionConfig",
    "LiveEvent",
    "TranscriptEvent",
    "AudioChunkEvent",
    "TurnCompleteEvent",
    "SetupCompleteEvent",
    "SynthesisRequest",
    "SynthesisResponse",
    "Speaker",
]
