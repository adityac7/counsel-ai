"""Input validation for WebSocket and API parameters."""

from __future__ import annotations

import re


class ValidationError(ValueError):
    """Raised when input validation fails."""


def validate_ws_params(params: dict) -> dict:
    """Sanitize and validate WebSocket query parameters.

    Returns cleaned params dict. Raises ValidationError on invalid input.
    """
    cleaned = {}

    # Name: max 100 chars, alphanumeric + spaces + common Indian name chars
    name = str(params.get("name", "Student"))[:100].strip()
    if not re.match(r"^[\w\s.\-']+$", name, re.UNICODE):
        name = re.sub(r"[^\w\s.\-']", "", name, flags=re.UNICODE)
    cleaned["name"] = name or "Student"

    # Grade: must be 9-12
    try:
        grade = int(params.get("grade", "9"))
        if grade < 9 or grade > 12:
            grade = 9
    except (ValueError, TypeError):
        grade = 9
    cleaned["grade"] = str(grade)

    # Age: must be 10-20
    try:
        age = int(params.get("age", "15"))
        if age < 10 or age > 20:
            age = 15
    except (ValueError, TypeError):
        age = 15
    cleaned["age"] = age

    # Section: max 10 chars, alphanumeric
    section = str(params.get("section", ""))[:10].strip()
    cleaned["section"] = re.sub(r"[^\w\s]", "", section)

    # School: max 200 chars
    cleaned["school"] = str(params.get("school", ""))[:200].strip()

    # Scenario: max 2000 chars
    cleaned["scenario"] = str(params.get("scenario", "General counselling session"))[:2000].strip()

    # Language: whitelist
    lang = str(params.get("lang", "hinglish"))
    cleaned["lang"] = lang if lang in ("hinglish", "en", "hi") else "hinglish"

    return cleaned
