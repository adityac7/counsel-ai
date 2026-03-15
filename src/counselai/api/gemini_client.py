"""Gemini client initialization and management.

Provides a singleton async-safe Gemini client, pre-initialized at startup.
"""

import logging
import os

from google import genai
from google.genai import types as gt

from counselai.api.exceptions import GeminiAPIKeyMissing, GeminiClientError

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
GEMINI_LIVE_MODEL = "models/gemini-2.5-flash-native-audio-preview-12-2025"
GEMINI_TRANSCRIPTION_MODEL = "models/gemini-3.1-flash-lite-preview"

# ---------------------------------------------------------------------------
# Singleton client
# ---------------------------------------------------------------------------
_client: genai.Client | None = None


def init_gemini_client() -> genai.Client:
    """Create and cache the Gemini client. Call once at startup."""
    global _client
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        raise GeminiAPIKeyMissing("GEMINI_API_KEY environment variable is not set")
    _client = genai.Client(
        api_key=api_key,
        http_options={"api_version": "v1beta"},
    )
    logger.info("Gemini client initialized")
    return _client


def get_gemini_client() -> genai.Client:
    """Return the cached client, initializing lazily if needed."""
    global _client
    if _client is None:
        return init_gemini_client()
    return _client


def build_live_config(resumption_handle: str | None = None) -> gt.LiveConnectConfig:
    """Build the LiveConnectConfig for audio-output sessions.

    Includes:
    - context_window_compression: extends audio+video from 2min to unlimited
    - session_resumption: survives 10min connection limit with auto-reconnect
    """
    return gt.LiveConnectConfig(
        response_modalities=["AUDIO"],
        speech_config=gt.SpeechConfig(
            voice_config=gt.VoiceConfig(
                prebuilt_voice_config=gt.PrebuiltVoiceConfig(voice_name="Zephyr")
            )
        ),
        input_audio_transcription=gt.AudioTranscriptionConfig(),
        output_audio_transcription=gt.AudioTranscriptionConfig(),
        context_window_compression=gt.ContextWindowCompressionConfig(
            sliding_window=gt.SlidingWindow(),
        ),
        session_resumption=gt.SessionResumptionConfig(
            handle=resumption_handle,
        ),
    )
