"""Logging configuration for the CounselAI application.

Uses JSON format in production (for log aggregation) and
human-readable format when COUNSELAI_DEBUG=true.
"""

import json
import logging
import sys
from datetime import datetime, timezone


class JSONFormatter(logging.Formatter):
    """Emit log records as single-line JSON objects."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        request_id = getattr(record, "request_id", None)
        if request_id:
            log_entry["request_id"] = request_id
        if record.exc_info and record.exc_info[1]:
            log_entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_entry, default=str)


def setup_logging() -> None:
    """Configure the counselai logger.

    JSON format for production, human-readable when debug=True.
    """
    from counselai.settings import settings

    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    root = logging.getLogger("counselai")
    root.setLevel(level)

    if root.handlers:
        return  # Already configured

    handler = logging.StreamHandler(sys.stderr)

    if settings.debug:
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")
        )
    else:
        handler.setFormatter(JSONFormatter())

    root.addHandler(handler)
