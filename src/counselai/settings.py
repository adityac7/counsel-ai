"""Central configuration loaded from environment variables.

Every API key, model name, URL, and tunable constant lives here.
Import the singleton ``settings`` from anywhere in the codebase.
"""

from __future__ import annotations

from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Typed settings for CounselAI — single source of truth."""

    # ── Database ────────────────────────────────────────────────────────
    database_url: str = "sqlite+aiosqlite:///counselai.db"

    # ── Artifact storage ────────────────────────────────────────────────
    artifact_root: str = "artifacts"

    # ── Provider API keys ───────────────────────────────────────────────
    # Accepts both GEMINI_API_KEY and COUNSELAI_GEMINI_API_KEY
    gemini_api_key: str = Field(default="", validation_alias="GEMINI_API_KEY")

    # ── Gemini Live (real-time conversation) ────────────────────────────
    gemini_live_model: str = "gemini-2.5-flash-native-audio-preview-12-2025"
    gemini_live_voice: str = "Aoede"
    gemini_api_version: str = "v1beta"

    # ── Gemini Synthesis (post-session analysis / structured extraction) ─
    gemini_synthesis_model: str = "gemini-3.1-flash-lite-preview"
    gemini_synthesis_temperature: float = 0.2
    gemini_synthesis_max_tokens: int = 8192

    # ── Counsellor persona ──────────────────────────────────────────────
    counsellor_instructions: str = (
        "You are an experienced Indian school counsellor for classes 9-12. "
        "Your goal: make the STUDENT talk more, not you. You are evaluating them 360 degrees — "
        "emotional intelligence, decision-making, values, peer dynamics, self-awareness.\n\n"
        "See COUNSELLOR_INSTRUCTIONS in constants.py for the full prompt.\n"
    )

    # ── Session limits ──────────────────────────────────────────────────
    max_session_duration_seconds: int = 420  # 7 min
    session_wrapup_seconds: int = 90  # warn at 5:30

    # ── CORS ──────────────────────────────────────────────────────────
    cors_origins: str = ""  # comma-separated allowed origins; empty = "*"

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
