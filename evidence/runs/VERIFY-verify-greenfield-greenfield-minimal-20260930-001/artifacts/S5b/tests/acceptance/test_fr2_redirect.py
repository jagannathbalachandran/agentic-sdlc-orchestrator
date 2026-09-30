# Traces: FR-2.AC1, FR-2.AC2
"""Acceptance tests for GET /{code} (01-requirements.md FR-2,
02-design.md DD-3/DD-4 contract)."""

from __future__ import annotations

import json
from http.client import HTTPConnection
from urllib.parse import urlsplit


def _post_shorten(base_url: str, long_url: str) -> str:
    parts = urlsplit(base_url)
    conn = HTTPConnection(parts.hostname, parts.port)
    try:
        body = json.dumps({"long_url": long_url}).encode("utf-8")
        conn.request(
            "POST",
            "/shorten",
            body=body,
            headers={"Content-Type": "application/json"},
        )
        response = conn.getresponse()
        data = json.loads(response.read())
    finally:
        conn.close()
    code: str = data["code"]
    return code


def _get(base_url: str, path: str) -> tuple[int, dict[str, str]]:
    parts = urlsplit(base_url)
    conn = HTTPConnection(parts.hostname, parts.port)
    try:
        conn.request("GET", path)
        response = conn.getresponse()
        response.read()
        return response.status, dict(response.getheaders())
    finally:
        conn.close()


def test_known_code_redirects_to_original_long_url(base_url: str) -> None:
    long_url = "https://example.com/some/path"
    code = _post_shorten(base_url, long_url)

    status, headers = _get(base_url, f"/{code}")

    assert 300 <= status < 400
    assert headers.get("Location") == long_url


def test_unknown_code_returns_404_without_redirecting(base_url: str) -> None:
    status, headers = _get(base_url, "/this-code-was-never-issued")

    assert status == 404
    assert "Location" not in headers
