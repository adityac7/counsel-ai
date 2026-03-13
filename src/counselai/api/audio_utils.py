"""Audio processing, transcription, PCM utilities, and VAD.

Provides:
- PCM format validation (16-bit, 16kHz mono)
- Energy-based Voice Activity Detection with configurable threshold
- Audio level metering for frontend display
- Silent audio generation for Gemini greeting trigger
- Async background transcription via Gemini
"""

import asyncio
import logging
import math
import struct
from typing import NamedTuple

from google.genai import types as gt

from counselai.api.exceptions import TranscriptionError
from counselai.api.gemini_client import get_gemini_client, GEMINI_TRANSCRIPTION_MODEL

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# PCM format constants
PCM_SAMPLE_RATE = 16000  # Expected input sample rate (Hz)
PCM_BYTES_PER_SAMPLE = 2  # 16-bit = 2 bytes
PCM_CHANNELS = 1  # Mono

# VAD energy threshold — RMS energy below this is treated as silence.
# 0.01 is too low and picks up background noise (transcribed as Hindi gibberish).
# 0.04 is a good balance for typical laptop/phone mics.
VAD_ENERGY_THRESHOLD = 0.04

# Minimum audio duration (ms) to consider for speech
VAD_MIN_SPEECH_MS = 150

# Phrases that indicate no real speech was detected
_SKIP_PHRASES = frozenset([
    "silence", "no speech", "no clear speech",
    "no audio", "no words", "empty",
])


# ---------------------------------------------------------------------------
# Audio level metering
# ---------------------------------------------------------------------------

class AudioLevel(NamedTuple):
    """Audio level metrics for frontend display."""
    rms: float       # Root-mean-square energy [0.0, 1.0]
    peak: float      # Peak amplitude [0.0, 1.0]
    db: float        # RMS in decibels (dBFS), -inf for silence
    is_speech: bool   # Whether this chunk passes VAD threshold


def compute_audio_level(pcm_bytes: bytes) -> AudioLevel:
    """Compute audio level metrics from raw PCM 16-bit LE samples.

    Returns an AudioLevel with rms, peak, dB, and speech detection.
    Handles empty/malformed input gracefully.
    """
    if not pcm_bytes or len(pcm_bytes) < PCM_BYTES_PER_SAMPLE:
        return AudioLevel(rms=0.0, peak=0.0, db=-100.0, is_speech=False)

    try:
        # Truncate to even number of bytes
        usable = len(pcm_bytes) - (len(pcm_bytes) % PCM_BYTES_PER_SAMPLE)
        if usable == 0:
            return AudioLevel(rms=0.0, peak=0.0, db=-100.0, is_speech=False)

        num_samples = usable // PCM_BYTES_PER_SAMPLE
        samples = struct.unpack(f"<{num_samples}h", pcm_bytes[:usable])

        # Normalize to [-1.0, 1.0]
        peak_raw = max(abs(s) for s in samples) if samples else 0
        peak = peak_raw / 32768.0

        sum_sq = sum(s * s for s in samples)
        rms = math.sqrt(sum_sq / num_samples) / 32768.0

        db = 20.0 * math.log10(rms) if rms > 0 else -100.0

        return AudioLevel(
            rms=round(rms, 6),
            peak=round(peak, 6),
            db=round(db, 2),
            is_speech=rms >= VAD_ENERGY_THRESHOLD,
        )
    except (struct.error, ValueError, ZeroDivisionError) as exc:
        logger.debug("Audio level computation failed: %s", exc)
        return AudioLevel(rms=0.0, peak=0.0, db=-100.0, is_speech=False)


# ---------------------------------------------------------------------------
# PCM format validation
# ---------------------------------------------------------------------------

def validate_pcm_format(
    pcm_bytes: bytes,
    *,
    expected_rate: int = PCM_SAMPLE_RATE,
    max_duration_s: float = 30.0,
) -> tuple[bool, str]:
    """Validate that PCM bytes are plausibly 16-bit mono at the expected rate.

    Returns (is_valid, reason). Since raw PCM has no header, we check:
    - Non-empty
    - Even byte count (16-bit samples)
    - Reasonable duration (not excessively long)
    """
    if not pcm_bytes:
        return False, "Empty audio data"

    if len(pcm_bytes) % PCM_BYTES_PER_SAMPLE != 0:
        return False, f"Byte count {len(pcm_bytes)} not aligned to 16-bit samples"

    num_samples = len(pcm_bytes) // PCM_BYTES_PER_SAMPLE
    duration_s = num_samples / expected_rate
    if duration_s > max_duration_s:
        return False, f"Audio duration {duration_s:.1f}s exceeds max {max_duration_s}s"

    return True, "ok"


# ---------------------------------------------------------------------------
# Voice Activity Detection (energy-based)
# ---------------------------------------------------------------------------

def is_speech(pcm_bytes: bytes, threshold: float = VAD_ENERGY_THRESHOLD) -> bool:
    """Simple energy-based VAD. Returns True if RMS energy exceeds threshold.

    For real-time use — fast, no external dependencies.
    Threshold of 0.04 filters out typical background noise while
    catching normal speech volumes.
    """
    level = compute_audio_level(pcm_bytes)
    return level.rms >= threshold


def check_min_speech_duration(
    pcm_bytes: bytes,
    sample_rate: int = PCM_SAMPLE_RATE,
    min_ms: int = VAD_MIN_SPEECH_MS,
) -> bool:
    """Check if audio chunk is long enough to contain meaningful speech."""
    num_samples = len(pcm_bytes) // PCM_BYTES_PER_SAMPLE
    duration_ms = (num_samples / sample_rate) * 1000
    return duration_ms >= min_ms


# ---------------------------------------------------------------------------
# Silent audio generation
# ---------------------------------------------------------------------------

def generate_silent_audio(sample_rate: int = 24000, duration_ms: int = 100) -> bytes:
    """Generate silent PCM audio bytes to trigger Gemini greeting."""
    num_samples = int(sample_rate * duration_ms / 1000)
    return struct.pack("<" + "h" * num_samples, *([0] * num_samples))


# ---------------------------------------------------------------------------
# Transcription
# ---------------------------------------------------------------------------

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


async def transcribe_in_background(
    audio_bytes: bytes,
    mime_type: str = "audio/wav",
    callback=None,
) -> asyncio.Task:
    """Launch transcription as a background task — doesn't block the audio loop.

    Args:
        audio_bytes: Raw audio data to transcribe.
        mime_type: MIME type of the audio.
        callback: Optional async callable(text: str) invoked with result.

    Returns:
        The asyncio.Task running the transcription.
    """
    async def _run():
        try:
            text = await transcribe_audio(audio_bytes, mime_type)
            if callback and text:
                await callback(text)
            return text
        except TranscriptionError as exc:
            logger.warning("Background transcription failed: %s", exc)
            return ""

    task = asyncio.create_task(_run())
    return task
