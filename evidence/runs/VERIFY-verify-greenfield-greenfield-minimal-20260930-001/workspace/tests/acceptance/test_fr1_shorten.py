# Traces: FR-1.AC1, FR-1.AC2, FR-1.AC3
"""Acceptance tests for POST /shorten (01-requirements.md FR-1,
02-design.md DD-2/DD-4 contract)."""

from __future__ import annotations

import json
from http.client import HTTPConnection
from urllib.parse import urlsplit


def _post_shorten(base_url: str, payload: object) -> tuple[int, dict[str, object]]:
    parts = urlsplit(base_url)
    assert parts.hostname is not None
    conn = HTTPConnection(parts.hostname, parts.port)
    try:
        body = json.dumps(payload).encode("utf-8")
        conn.request(
            "POST",
            "/shorten",
            body=body,
            headers={"Content-Type": "application/json"},
        )
        response = conn.getresponse()
        raw = response.read()
        data = json.loads(raw) if raw else {}
        return response.status, data
    finally:
        conn.close()


def test_valid_long_url_returns_2xx_with_nonempty_distinct_code(base_url: str) -> None:
    long_url = "https://example.com/some/path"

    status, data = _post_shorten(base_url, {"long_url": long_url})

    assert 200 <= status < 300
    assert isinstance(data.get("code"), str)
    assert data["code"] != ""
    assert data["code"] != long_url


def test_two_shorten_requests_with_different_urls_get_different_codes(
    base_url: str,
) -> None:
    status_a, data_a = _post_shorten(base_url, {"long_url": "https://example.com/a"})
    status_b, data_b = _post_shorten(base_url, {"long_url": "https://example.com/b"})

    assert 200 <= status_a < 300
    assert 200 <= status_b < 300
    assert data_a["code"] != data_b["code"]


def test_missing_long_url_returns_4xx_and_creates_no_code(base_url: str) -> None:
    status, data = _post_shorten(base_url, {})

    assert 400 <= status < 500
    assert "code" not in data


def test_empty_long_url_returns_4xx_and_creates_no_code(base_url: str) -> None:
    status, data = _post_shorten(base_url, {"long_url": ""})

    assert 400 <= status < 500
    assert "code" not in data
