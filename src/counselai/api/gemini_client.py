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
GEMINI_LIVE_MODEL = "gemini-2.5-flash-native-audio-preview-12-2025"
GEMINI_ANALYSIS_MODEL = "gemini-3.1-flash-lite-preview"

# ---------------------------------------------------------------------------
# Function-calling tools for real-time signal extraction
# ---------------------------------------------------------------------------
LIVE_TOOLS = [
    gt.Tool(function_declarations=[
        gt.FunctionDeclaration(
            name="log_observation",
            description=(
                "Silently log a behavioral observation about the student. "
                "Call whenever you notice emotional shifts, hesitation, confusion, "
                "engagement changes, risk signals, or body language cues from audio/video. "
                "This is invisible to the student."
            ),
            parameters={
                "type": "OBJECT",
                "properties": {
                    "observation_type": {
                        "type": "STRING",
                        "enum": [
                            "emotional_shift", "hesitation", "confusion",
                            "engagement_change", "risk_signal", "insight_moment",
                            "avoidance", "body_language",
                        ],
                    },
                    "emotion": {"type": "STRING", "description": "Primary emotion detected (e.g. anxious, confused, confident, sad)"},
                    "confidence": {"type": "NUMBER", "description": "0.0 to 1.0 — how confident you are in this observation"},
                    "modality": {
                        "type": "STRING",
                        "enum": ["audio", "video", "content", "cross_modal"],
                        "description": "Which signal source triggered this observation",
                    },
                    "description": {"type": "STRING", "description": "What you observed and why it matters for the student's profile"},
                },
                "required": ["observation_type", "emotion", "confidence", "modality", "description"],
            },
        ),
        gt.FunctionDeclaration(
            name="segment_transition",
            description=(
                "Signal that the conversation has moved to a new case study part or question. "
                "Call when the topic shifts to a distinct new aspect of the scenario."
            ),
            parameters={
                "type": "OBJECT",
                "properties": {
                    "segment_name": {"type": "STRING", "description": "Short label for the new segment/topic"},
                    "reason": {"type": "STRING", "description": "Why you detected a segment boundary"},
                },
                "required": ["segment_name", "reason"],
            },
        ),
    ])
]

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
        http_options={"api_version": "v1alpha"},
    )
    logger.info("Gemini client initialized (v1alpha)")
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
    """Build the LiveConnectConfig for audio-output sessions.

    Now includes:
    - Function-calling tools for real-time signal extraction
    - System instruction in config (instead of send_client_content)
    - Proactive audio (Gemini ignores non-directed background speech)
    """
    config = gt.LiveConnectConfig(
        response_modalities=["AUDIO"],
        speech_config=gt.SpeechConfig(
            voice_config=gt.VoiceConfig(
                prebuilt_voice_config=gt.PrebuiltVoiceConfig(voice_name="Aoede")
            )
        ),
        input_audio_transcription=gt.AudioTranscriptionConfig(),
        output_audio_transcription=gt.AudioTranscriptionConfig(),
        tools=LIVE_TOOLS,
        proactivity={"proactive_audio": True},
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
