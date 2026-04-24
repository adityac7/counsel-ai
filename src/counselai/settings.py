"""Central configuration loaded from environment variables.

Every API key, model name, URL, and tunable constant lives here.
Import the singleton ``settings`` from anywhere in the codebase.
"""

from __future__ import annotations

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Typed settings for CounselAI — single source of truth."""

    # ── Database ────────────────────────────────────────────────────────
    database_url: str = "sqlite+aiosqlite:///counselai.db"

    # ── Gemini provider selection ───────────────────────────────────────
    # Allowed: "ai_studio" (default) | "vertex"
    gemini_provider: str = Field(default="ai_studio", validation_alias="GEMINI_PROVIDER")

    # ── Google AI Studio credentials (gemini_provider=ai_studio) ────────
    # Accepts GOOGLE_API_KEY or the legacy GEMINI_API_KEY
    gemini_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("GOOGLE_API_KEY", "GEMINI_API_KEY"),
    )

    # ── Vertex AI credentials (gemini_provider=vertex) ──────────────────
    # Base64-encoded service account JSON — set GOOGLE_SERVICE_ACCOUNT_JSON_B64
    # to the output of: base64 -w0 service-account.json
    google_cloud_project: str = Field(default="", validation_alias="GOOGLE_CLOUD_PROJECT")
    google_cloud_location: str = Field(default="us-central1", validation_alias="GOOGLE_CLOUD_LOCATION")
    google_service_account_b64: str = Field(default="", validation_alias="GOOGLE_SERVICE_ACCOUNT_JSON_B64")

    # ── Gemini Live (real-time conversation) ────────────────────────────
    gemini_live_model: str = "gemini-2.5-flash-native-audio-preview-12-2025"
    gemini_live_voice: str = "Aoede"
    gemini_api_version: str = "v1beta"

    # ── Gemini Synthesis (post-session analysis / structured extraction) ─
    gemini_synthesis_model: str = "gemini-2.5-flash"
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
    max_session_duration_seconds: int = 300  # 5 min
    session_wrapup_seconds: int = 90  # warn at 3:30, hard timeout at 5:00

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


# Module-level singleton — import this everywhere.
settings = Settings()
