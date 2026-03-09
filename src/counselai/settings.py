"""Central configuration loaded from environment variables.

Every API key, model name, URL, and tunable constant lives here.
Import the singleton ``settings`` from anywhere in the codebase.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Typed settings for CounselAI — single source of truth."""

    # ── Database ────────────────────────────────────────────────────────
    database_url: str = "postgresql://counselai:counselai@localhost:5432/counselai"

    # ── Artifact storage ────────────────────────────────────────────────
    artifact_root: str = "artifacts"

    # ── Provider API keys ───────────────────────────────────────────────
    gemini_api_key: str = ""
    openai_api_key: str = ""

    # ── Gemini Live (real-time conversation) ────────────────────────────
    gemini_live_model: str = "models/gemini-2.5-flash-native-audio-preview-12-2025"
    gemini_live_voice: str = "Zephyr"
    gemini_api_version: str = "v1beta"

    # ── Gemini Synthesis (post-session analysis / structured extraction) ─
    gemini_synthesis_model: str = "models/gemini-3.1-flash-lite-preview"
    gemini_synthesis_temperature: float = 0.2
    gemini_synthesis_max_tokens: int = 8192

    # ── OpenAI Realtime (live conversation) ─────────────────────────────
    openai_realtime_model: str = "gpt-realtime"
    openai_realtime_voice: str = "sage"
    openai_realtime_url: str = "https://api.openai.com/v1/realtime/calls"
    openai_transcription_model: str = "gpt-4o-transcribe"

    # ── OpenAI Synthesis (post-session analysis) ────────────────────────
    openai_synthesis_model: str = "gpt-4.1-mini"
    openai_synthesis_temperature: float = 0.2
    openai_synthesis_max_tokens: int = 8192

    # ── Live session defaults ───────────────────────────────────────────
    default_live_provider: Literal["gemini-live", "openai-realtime"] = "gemini-live"
    default_synthesis_provider: Literal["gemini", "openai"] = "gemini"

    # ── Counsellor persona ──────────────────────────────────────────────
    counsellor_instructions: str = (
        "You are an experienced Indian school counsellor for classes 9-12. "
        "Your goal: make the STUDENT talk more, not you. You are evaluating them 360 degrees — "
        "emotional intelligence, decision-making, values, peer dynamics, self-awareness.\n\n"
        "RULES:\n"
        "- Keep your responses SHORT: 1-2 sentences max. Your job is to LISTEN and PROBE.\n"
        "- Ask ONE precise question per turn. Make it count.\n"
        "- Do NOT mirror or repeat what the student said. No paraphrasing back.\n"
        "- Only repeat if you genuinely need clarification on something unclear.\n"
        "- Do NOT be overly warm or verbose. No \"wah\", \"bahut accha\", \"kya baat hai\". "
        "Be natural, not theatrical.\n"
        "- Use casual Hinglish naturally: beta, accha, hmm, aur, theek hai.\n"
        "- Your questions should dig deeper each time — move from surface to values to feelings.\n"
        "- Cover multiple angles: what they think, what they feel, what they would do, "
        "what they fear, what matters most to them.\n"
        "- End the session after 8-10 exchanges. Wrap up naturally: \"Accha beta, bahut acchi "
        "baat ki tumne. Thank you.\"\n"
        "- For the first response: briefly greet by name, read the case study concisely in "
        "Hinglish, then immediately ask the first probing question.\n"
        "- Do NOT lecture. Do NOT give advice. Do NOT analyze during the session.\n\n"
    )

    # ── Worker / Redis ──────────────────────────────────────────────────
    redis_url: str = "redis://localhost:6379/0"

    # ── Processing pipeline ─────────────────────────────────────────────
    processing_version: str = "v1"
    max_session_turns: int = 30
    max_session_duration_seconds: int = 1800  # 30 min

    # ── Audio analysis ──────────────────────────────────────────────────
    audio_sample_rate: int = 24000

    # ── Logging ─────────────────────────────────────────────────────────
    log_level: str = "INFO"
    debug: bool = False

    model_config = {
        "env_prefix": "COUNSELAI_",
        "env_file": ".env",
        "extra": "ignore",
    }

    @property
    def artifact_path(self) -> Path:
        return Path(self.artifact_root)


# Module-level singleton — import this everywhere.
settings = Settings()
