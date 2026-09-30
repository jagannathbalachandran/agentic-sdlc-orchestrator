# Traces: FR-1.AC1, FR-1.AC2, FR-1.AC3
"""Acceptance tests for POST /shorten, derived from 01-requirements.md and
the response contract in 02-design.md's DD-1/DD-2 (no src/ inspection)."""
from __future__ import annotations

import json

import pytest

from .conftest import ServiceClient


def test_valid_url_returns_2xx_with_nonempty_new_code(client: ServiceClient) -> None:
    """FR-1.AC1: a valid absolute http(s) URL yields 2xx and a non-empty code."""
    status, payload = client.shorten(json.dumps({"url": "http://example.com/page"}).encode())

    assert 200 <= status < 300
    assert isinstance(payload.get("code"), str)
    assert payload["code"] != ""


def test_valid_https_url_is_accepted(client: ServiceClient) -> None:
    """FR-1.AC1: https scheme is accepted as well as http."""
    status, payload = client.shorten(json.dumps({"url": "https://example.com/secure"}).encode())

    assert 200 <= status < 300
    assert payload["code"] != ""


@pytest.mark.parametrize(
    "body",
    [
        b"{}",
        json.dumps({"url": ""}).encode(),
        json.dumps({"url": "not-a-url"}).encode(),
        json.dumps({"url": "ftp://example.com/file"}).encode(),
        json.dumps({"not_url": "http://example.com"}).encode(),
        b"not even json",
    ],
    ids=[
        "missing-url-key",
        "empty-url",
        "malformed-no-scheme",
        "unsupported-scheme",
        "wrong-key",
        "unparsable-json",
    ],
)
def test_invalid_body_returns_4xx_and_creates_nothing(client: ServiceClient, body: bytes) -> None:
    """FR-1.AC2: missing/empty/malformed URL yields 4xx and no code is created."""
    status, payload = client.shorten(body)

    assert 400 <= status < 500
    assert "code" not in payload


def test_two_successful_calls_return_distinct_codes(client: ServiceClient) -> None:
    """FR-1.AC3: two successful POST /shorten calls return distinct codes,
    even for the same long URL."""
    url = "http://example.com/same-url-twice"
    status_a, payload_a = client.shorten(json.dumps({"url": url}).encode())
    status_b, payload_b = client.shorten(json.dumps({"url": url}).encode())

    assert 200 <= status_a < 300
    assert 200 <= status_b < 300
    assert payload_a["code"] != payload_b["code"]


def test_two_successful_calls_with_different_urls_return_distinct_codes(
    client: ServiceClient,
) -> None:
    """FR-1.AC3: distinct codes also hold across different long URLs."""
    status_a, payload_a = client.shorten(json.dumps({"url": "http://example.com/a"}).encode())
    status_b, payload_b = client.shorten(json.dumps({"url": "http://example.com/b"}).encode())

    assert 200 <= status_a < 300
    assert 200 <= status_b < 300
    assert payload_a["code"] != payload_b["code"]
