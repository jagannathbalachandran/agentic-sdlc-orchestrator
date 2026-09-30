# Traces: FR-1.AC1, FR-1.AC2, FR-1.AC3
"""Acceptance tests for POST /shorten (FR-1), derived from
01-requirements.md acceptance criteria and 02-design.md DD-1/DD-2 contracts.
"""
from service.app import create_app


def make_client():
    app = create_app()
    return app.test_client()


def test_valid_url_returns_2xx_with_new_short_code():
    """FR-1.AC1: valid URL -> 2xx status, body contains a short code not
    present in the request."""
    client = make_client()
    url = "https://example.com/some/long/path?q=1"

    response = client.post("/shorten", json={"url": url})

    assert 200 <= response.status_code < 300
    body = response.get_json()
    assert "code" in body
    code = body["code"]
    assert isinstance(code, str)
    assert code != "" and code not in url


def test_missing_url_field_returns_4xx_and_generates_nothing():
    """FR-1.AC2: missing URL field -> 4xx, and the (absent) code must never
    resolve, i.e. nothing was generated/stored."""
    client = make_client()

    response = client.post("/shorten", json={})

    assert 400 <= response.status_code < 500
    body = response.get_json()
    assert "code" not in body


def test_syntactically_invalid_url_returns_4xx():
    """FR-1.AC2: syntactically invalid URL -> 4xx status, no short code."""
    client = make_client()

    response = client.post("/shorten", json={"url": "not-a-valid-url"})

    assert 400 <= response.status_code < 500
    body = response.get_json()
    assert "code" not in body


def test_non_http_scheme_url_returns_4xx():
    """FR-1.AC2: scheme other than http/https is syntactically invalid per
    DD-2's validation contract -> 4xx, no short code generated."""
    client = make_client()

    response = client.post("/shorten", json={"url": "ftp://example.com/file"})

    assert 400 <= response.status_code < 500
    body = response.get_json()
    assert "code" not in body


def test_shortened_code_round_trips_to_exact_submitted_url():
    """FR-1.AC3: a code returned by /shorten resolves back to the exact
    (byte-for-byte) long URL that was submitted, with no normalization."""
    client = make_client()
    url = "https://example.com/some/path/?q=1&x=trailing/"

    shorten_response = client.post("/shorten", json={"url": url})
    assert 200 <= shorten_response.status_code < 300
    code = shorten_response.get_json()["code"]

    redirect_response = client.get(f"/{code}", follow_redirects=False)

    assert 300 <= redirect_response.status_code < 400
    assert redirect_response.headers["Location"] == url
