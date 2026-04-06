"""Custom exceptions for CounselAI API."""


class CounselAIError(Exception):
    """Base exception for all CounselAI errors."""


class GeminiClientError(CounselAIError):
    """Raised when Gemini client initialization or calls fail."""


class GeminiAPIKeyMissing(GeminiClientError):
    """Raised when GEMINI_API_KEY env var is not set."""


class TranscriptionError(CounselAIError):
    """Raised when audio transcription fails."""
