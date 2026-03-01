"""Audio transcription using OpenAI Whisper API."""
from __future__ import annotations

import os
from typing import Any, Dict, List

from pydub import AudioSegment

try:
    from openai import OpenAI
except Exception:  # pragma: no cover - import guard for runtime envs
    OpenAI = None  # type: ignore


def transcribe_audio(audio_path: str) -> Dict[str, Any]:
    """Transcribe an audio file with OpenAI Whisper and return text + segments."""
    print(f"[transcriber] Starting transcription for {audio_path}")

    if not audio_path or not os.path.exists(audio_path):
        print("[transcriber] Error: file not found")
        return {}

    if os.path.getsize(audio_path) == 0:
        print("[transcriber] Error: empty audio file")
        return {}

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("[transcriber] Error: OPENAI_API_KEY is not set")
        return {}

    if OpenAI is None:
        print("[transcriber] Error: openai package is not available")
        return {}

    duration = None
    try:
        audio = AudioSegment.from_file(audio_path)
        duration = len(audio) / 1000.0
        if duration <= 0:
            print("[transcriber] Error: empty audio content")
            return {}
    except Exception as exc:
        print(f"[transcriber] Warning: could not read audio duration ({exc})")

    try:
        client = OpenAI(api_key=api_key)
        with open(audio_path, "rb") as audio_file:
            response = client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
                response_format="verbose_json",
            )
    except Exception as exc:
        print(f"[transcriber] Error: Whisper API failure ({exc})")
        return {}

    if not response:
        print("[transcriber] Error: empty response from Whisper")
        return {}

    text = getattr(response, "text", "") or response.get("text", "")
    segments_raw = getattr(response, "segments", None) or response.get("segments", [])
    duration = getattr(response, "duration", None) or response.get("duration", duration)

    if not text:
        print("[transcriber] Warning: no transcript text returned")

    segments: List[Dict[str, Any]] = []
    if segments_raw:
        for seg in segments_raw:
            try:
                segments.append(
                    {
                        "start": float(seg.get("start", 0.0)),
                        "end": float(seg.get("end", 0.0)),
                        "text": seg.get("text", ""),
                    }
                )
            except Exception:
                continue

    result = {"text": text, "segments": segments, "duration": float(duration or 0.0)}
    print("[transcriber] Transcription complete")
    return result
