"""Audio processing, transcription, and PCM utilities."""

import logging
import struct

from google.genai import types as gt

from counselai.api.exceptions import TranscriptionError
from counselai.api.gemini_client import get_gemini_client, GEMINI_TRANSCRIPTION_MODEL

logger = logging.getLogger(__name__)

# Phrases that indicate no real speech was detected
_SKIP_PHRASES = [
    "silence", "no speech", "no clear speech",
    "no audio", "no words", "empty",
]


def generate_silent_audio(sample_rate: int = 24000, duration_ms: int = 100) -> bytes:
    """Generate silent PCM audio bytes to trigger Gemini greeting."""
    num_samples = int(sample_rate * duration_ms / 1000)
    return struct.pack("<" + "h" * num_samples, *([0] * num_samples))


async def transcribe_audio(audio_bytes: bytes, mime_type: str = "audio/wav") -> str:
    """Transcribe audio bytes using Gemini.

    Returns the transcribed text, or empty string if no speech detected.
    Raises TranscriptionError on failure.
    """
    try:
        client = get_gemini_client()
        response = client.models.generate_content(
            model=GEMINI_TRANSCRIPTION_MODEL,
            contents=[
                "Transcribe the human speech in this audio to text. Return ONLY the exact "
                "spoken words in the original language (Hindi/Hinglish/English). If there is "
                "no clear speech, return an empty string. Do NOT describe sounds or noises.",
                gt.Part.from_bytes(data=audio_bytes, mime_type=mime_type),
            ],
            config=gt.GenerateContentConfig(),
        )
        text = (response.text or "").strip()
        if any(s in text.lower() for s in _SKIP_PHRASES) and len(text) < 50:
            text = ""
        return text
    except Exception as exc:
        logger.error("Transcription failed: %s", exc)
        raise TranscriptionError(str(exc)) from exc
