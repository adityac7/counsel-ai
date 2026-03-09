"""Logging configuration for the CounselAI application."""

import logging
import sys


def setup_logging(level: int = logging.INFO) -> None:
    root = logging.getLogger("counselai")
    root.setLevel(level)
    if not root.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")
        )
        root.addHandler(handler)
