"""Custom exceptions for CounselAI API."""


class CounselAIError(Exception):
    """Base exception for all CounselAI errors."""


class GeminiClientError(CounselAIError):
    """Raised when Gemini client initialization or calls fail."""


class GeminiAPIKeyMissing(GeminiClientError):
    """Raised when GEMINI_API_KEY env var is not set."""


class TranscriptionError(CounselAIError):
    """Raised when audio transcription fails."""


class WebSocketSessionError(CounselAIError):
    """Raised when a WebSocket session encounters an unrecoverable error."""


class InsufficientSessionData(CounselAIError):
    """Raised when session data is too sparse for analysis."""

    def __init__(self, msg: str = "Insufficient session data for analysis."):
        super().__init__(msg)
