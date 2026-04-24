"""Gemini client initialization and management.

Provides a singleton async-safe Gemini client, pre-initialized at startup.
"""

import base64
import json
import logging

from google import genai
from google.genai import types as gt
from google.oauth2 import service_account

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


def _decode_service_account_b64() -> dict:
    """Decode GOOGLE_SERVICE_ACCOUNT_JSON_B64 → parsed service-account dict."""
    raw = settings.google_service_account_b64
    if not raw:
        raise GeminiClientError(
            "GOOGLE_SERVICE_ACCOUNT_JSON_B64 is required when GEMINI_PROVIDER=vertex"
        )
    try:
        sa_info = json.loads(base64.b64decode(raw).decode("utf-8"))
    except Exception as exc:
        raise GeminiClientError(
            f"Failed to decode GOOGLE_SERVICE_ACCOUNT_JSON_B64: {exc}"
        ) from exc
    return sa_info


def init_gemini_client() -> genai.Client:
    """Create and cache the Gemini client. Call once at startup.

    Provider is chosen entirely from ENV:
      GEMINI_PROVIDER=ai_studio  →  Google AI Studio (needs GOOGLE_API_KEY)
      GEMINI_PROVIDER=vertex     →  Vertex AI (needs GOOGLE_CLOUD_PROJECT +
                                    GOOGLE_CLOUD_LOCATION +
                                    GOOGLE_SERVICE_ACCOUNT_JSON_B64)
    """
    global _client
    provider = settings.gemini_provider.lower()

    if provider == "vertex":
        project = settings.google_cloud_project
        location = settings.google_cloud_location
        if not project:
            raise GeminiClientError(
                "GOOGLE_CLOUD_PROJECT is required when GEMINI_PROVIDER=vertex"
            )
        if not location:
            raise GeminiClientError(
                "GOOGLE_CLOUD_LOCATION is required when GEMINI_PROVIDER=vertex"
            )
        sa_info = _decode_service_account_b64()
        credentials = service_account.Credentials.from_service_account_info(
            sa_info,
            scopes=["https://www.googleapis.com/auth/cloud-platform"],
        )
        _client = genai.Client(
            vertexai=True,
            project=project,
            location=location,
            credentials=credentials,
        )
        logger.info(
            "Using Gemini Provider: Vertex AI (project=%s, location=%s, sa=%s)",
            project, location, sa_info.get("client_email", "unknown"),
        )
    else:
        # Default: Google AI Studio
        api_key = settings.gemini_api_key
        if not api_key:
            raise GeminiAPIKeyMissing(
                "GOOGLE_API_KEY is required when GEMINI_PROVIDER=ai_studio"
            )
        _client = genai.Client(
            api_key=api_key,
            http_options={"api_version": settings.gemini_api_version},
        )
        logger.info("Using Gemini Provider: Google AI Studio (%s)", settings.gemini_api_version)

    return _client


def get_gemini_client() -> genai.Client:
    """Return the cached client, initializing lazily if needed."""
    global _client
    if _client is None:
        return init_gemini_client()
    return _client


# BCP-47 code for SpeechConfig.language_code (voice TTS output).
# Hinglish uses "en-IN" since the counsellor speaks Roman-script Hinglish.
# Note: AudioTranscriptionConfig.language_codes is SDK-exposed but rejected
# by the live API — language steering for transcription is done via system_instruction.
_SPEECH_LANGUAGE_CODE = {
    "en": "en-US",
    "hi": "hi-IN",
    "hinglish": "en-US",
}


def build_live_config(
    resumption_handle: str | None = None,
    language: str = "hinglish",
    system_instruction: str = "",
) -> gt.LiveConnectConfig:
    """Build the LiveConnectConfig for audio-output sessions."""
    speech_lang = _SPEECH_LANGUAGE_CODE.get(language, "en-IN")
    config = gt.LiveConnectConfig(
        response_modalities=["AUDIO"],
        speech_config=gt.SpeechConfig(
            language_code=speech_lang,
            voice_config=gt.VoiceConfig(
                prebuilt_voice_config=gt.PrebuiltVoiceConfig(voice_name="Aoede")
            )
        ),
        input_audio_transcription=gt.AudioTranscriptionConfig(),
        output_audio_transcription=gt.AudioTranscriptionConfig(),
        # Use low-resolution media tokens to cut video frame costs ~4x.
        media_resolution=gt.MediaResolution.MEDIA_RESOLUTION_LOW,
        # Faster turn detection: high end-of-speech sensitivity + shorter
        # silence window (default ~800 ms → 500 ms reduces response latency).
        realtime_input_config=gt.RealtimeInputConfig(
            automatic_activity_detection=gt.AutomaticActivityDetection(
                end_of_speech_sensitivity=gt.EndSensitivity.END_SENSITIVITY_HIGH,
                silence_duration_ms=500,
            )
        ),
        # Disable thinking tokens — 2.5 flash spends ~5s "thinking" before
        # producing audio which causes the long initial silence. Setting
        # budget=0 makes it respond immediately like a non-thinking model.
        generation_config=gt.GenerationConfig(
            thinking_config=gt.ThinkingConfig(thinking_budget=0),
        ),
        # Sliding-window compression prevents the context from filling up
        # mid-session and triggering 1011 internal errors after a few turns.
        context_window_compression=gt.ContextWindowCompressionConfig(
            sliding_window=gt.SlidingWindow(),
            trigger_tokens=25600,
        ),
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
