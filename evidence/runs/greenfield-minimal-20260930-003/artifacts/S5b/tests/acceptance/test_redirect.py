# Traces: FR-2.AC1, FR-2.AC2
"""Acceptance tests for GET /{code}, derived from 01-requirements.md and
the response contract in 02-design.md's DD-1 (no src/ inspection)."""
from __future__ import annotations

import json

from .conftest import ServiceClient


def test_known_code_redirects_with_exact_location(client: ServiceClient) -> None:
    """FR-2.AC1: GET /{code} for a code from a successful POST /shorten
    returns a 3xx redirect whose Location header equals the original URL
    exactly."""
    original_url = "http://example.com/exact/path?query=1&other=2"
    status, payload = client.shorten(json.dumps({"url": original_url}).encode())
    assert 200 <= status < 300
    code = payload["code"]

    redirect_status, location, _body = client.get_redirect(code)

    assert 300 <= redirect_status < 400
    assert location == original_url


def test_unknown_code_returns_404(client: ServiceClient) -> None:
    """FR-2.AC2: a code never returned by POST /shorten yields 404."""
    status, _location, _body = client.get_redirect("thiscodewasneverissued123")

    assert status == 404


def test_distinct_codes_redirect_to_their_own_urls(client: ServiceClient) -> None:
    """FR-2.AC1: multiple registered codes each redirect to their own,
    distinct original URL (Location is per-code, not a fixed value)."""
    url_a = "http://example.com/first"
    url_b = "http://example.com/second"
    _status_a, payload_a = client.shorten(json.dumps({"url": url_a}).encode())
    _status_b, payload_b = client.shorten(json.dumps({"url": url_b}).encode())

    status_a, location_a, _ = client.get_redirect(payload_a["code"])
    status_b, location_b, _ = client.get_redirect(payload_b["code"])

    assert 300 <= status_a < 400
    assert 300 <= status_b < 400
    assert location_a == url_a
    assert location_b == url_b
