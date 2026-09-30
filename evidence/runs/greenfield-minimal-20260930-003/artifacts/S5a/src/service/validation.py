"""Request-body validation for POST /shorten (DD-2)."""

import json
from urllib.parse import urlsplit


class ValidationError(ValueError):
    """Raised when the /shorten request body fails validation."""


def parse_shorten_body(raw_body: bytes) -> str:
    """Parse and validate a POST /shorten body.

    Returns the validated absolute http/https URL on success.
    Raises ValidationError for: unparsable JSON, missing/non-string/empty
    "url" field, or a URL whose scheme is not exactly "http" or "https"
    (per urllib.parse.urlsplit) — covers FR-1.AC2 (missing, empty, or
    malformed URL).
    """
    try:
        data = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        raise ValidationError("request body is not valid JSON") from exc

    if not isinstance(data, dict):
        raise ValidationError("request body must be a JSON object")

    url = data.get("url")
    if not isinstance(url, str) or not url:
        raise ValidationError("\"url\" must be a non-empty string")

    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise ValidationError("\"url\" must be an absolute http/https URL")

    return url
