"""Gemini client initialization and management.

Provides a singleton async-safe Gemini client, pre-initialized at startup.
"""

import logging

from google import genai
from google.genai import types as gt

from counselai.api.exceptions import GeminiAPIKeyMissing, GeminiClientError
from counselai.settings import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Model name aliases (from settings singleton)
# ---------------------------------------------------------------------------
GEMINI_LIVE_MODEL = settings.gemini_live_model
GEMINI_ANALYSIS_MODEL = settings.gemini_synthesis_model

# ---------------------------------------------------------------------------
# Singleton client
# ---------------------------------------------------------------------------
_client: genai.Client | None = None


def init_gemini_client() -> genai.Client:
    """Create and cache the Gemini client. Call once at startup."""
    global _client
    api_key = settings.gemini_api_key
    if not api_key:
        raise GeminiAPIKeyMissing("GEMINI_API_KEY environment variable is not set")
    _client = genai.Client(
        api_key=api_key,
        http_options={"api_version": settings.gemini_api_version},
    )
    logger.info("Gemini client initialized (%s)", settings.gemini_api_version)
    return _client


def get_gemini_client() -> genai.Client:
    """Return the cached client, initializing lazily if needed."""
    global _client
    if _client is None:
        return init_gemini_client()
    return _client


def build_live_config(
    resumption_handle: str | None = None,
    language: str = "hinglish",
    system_instruction: str = "",
) -> gt.LiveConnectConfig:
    """Build the LiveConnectConfig for audio-output sessions."""

    config = gt.LiveConnectConfig(
        response_modalities=["AUDIO"],
        speech_config=gt.SpeechConfig(
            voice_config=gt.VoiceConfig(
                prebuilt_voice_config=gt.PrebuiltVoiceConfig(voice_name="Aoede")
            )
        ),
        input_audio_transcription=gt.AudioTranscriptionConfig(),
        output_audio_transcription=gt.AudioTranscriptionConfig(),
    )

    # System instruction — set in config so it's processed at setup time
    if system_instruction:
        config.system_instruction = system_instruction

    # Session resumption — only include handle if we have one from a prior connection
    if resumption_handle:
        config.session_resumption = gt.SessionResumptionConfig(
            handle=resumption_handle,
        )

    return config
