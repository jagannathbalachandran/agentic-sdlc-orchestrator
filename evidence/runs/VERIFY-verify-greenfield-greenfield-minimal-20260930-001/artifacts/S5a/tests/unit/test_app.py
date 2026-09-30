from __future__ import annotations

import io
import json
from wsgiref.util import setup_testing_defaults

import pytest

from service.app import (
    ValidationError,
    create_app,
    handle_redirect,
    handle_shorten,
    validate_long_url,
)
from service.store import InMemoryCodeStore


def _call_app(app, method: str, path: str, body: bytes = b"") -> tuple[str, list, bytes]:
    environ = {}
    setup_testing_defaults(environ)
    environ["REQUEST_METHOD"] = method
    environ["PATH_INFO"] = path
    environ["CONTENT_LENGTH"] = str(len(body))
    environ["wsgi.input"] = io.BytesIO(body)

    captured = {}

    def start_response(status, headers):
        captured["status"] = status
        captured["headers"] = headers

    response_body = b"".join(app(environ, start_response))
    return captured["status"], captured["headers"], response_body


def test_validate_long_url_accepts_http_url() -> None:
    assert validate_long_url("http://example.com") == "http://example.com"


def test_validate_long_url_accepts_https_url() -> None:
    url = "https://example.com/some/path"

    assert validate_long_url(url) == url


def test_validate_long_url_rejects_empty_string() -> None:
    with pytest.raises(ValidationError):
        validate_long_url("")


def test_validate_long_url_rejects_none() -> None:
    with pytest.raises(ValidationError):
        validate_long_url(None)


def test_validate_long_url_rejects_non_string() -> None:
    with pytest.raises(ValidationError):
        validate_long_url(123)


def test_validate_long_url_rejects_unsupported_scheme() -> None:
    with pytest.raises(ValidationError):
        validate_long_url("ftp://example.com/file")


def test_validate_long_url_rejects_missing_scheme() -> None:
    with pytest.raises(ValidationError):
        validate_long_url("example.com/path")


def test_validate_long_url_rejects_empty_netloc() -> None:
    with pytest.raises(ValidationError):
        validate_long_url("http:///path")


def test_validation_error_is_a_value_error() -> None:
    assert issubclass(ValidationError, ValueError)


def test_handle_shorten_returns_201_and_code_for_valid_url() -> None:
    store = InMemoryCodeStore()

    status, payload = handle_shorten(
        json.dumps({"long_url": "https://example.com"}), store
    )

    assert status == 201
    assert store.resolve(payload["code"]) == "https://example.com"


def test_handle_shorten_returns_400_for_invalid_url() -> None:
    store = InMemoryCodeStore()

    status, payload = handle_shorten(json.dumps({"long_url": "not-a-url"}), store)

    assert status == 400
    assert "error" in payload


def test_handle_shorten_returns_400_for_missing_long_url() -> None:
    store = InMemoryCodeStore()

    status, payload = handle_shorten(json.dumps({}), store)

    assert status == 400
    assert "error" in payload


def test_handle_shorten_returns_400_for_malformed_json() -> None:
    store = InMemoryCodeStore()

    status, payload = handle_shorten("not json", store)

    assert status == 400
    assert "error" in payload


def test_handle_shorten_returns_400_for_non_object_json() -> None:
    store = InMemoryCodeStore()

    status, payload = handle_shorten(json.dumps(["long_url"]), store)

    assert status == 400
    assert "error" in payload


def test_handle_shorten_accepts_bytes_body() -> None:
    store = InMemoryCodeStore()

    status, payload = handle_shorten(
        json.dumps({"long_url": "https://example.com"}).encode("utf-8"), store
    )

    assert status == 201
    assert "code" in payload


def test_handle_redirect_returns_302_and_location_for_known_code() -> None:
    store = InMemoryCodeStore()
    code = store.save("https://example.com")

    status, payload = handle_redirect(code, store)

    assert status == 302
    assert payload == {"Location": "https://example.com"}


def test_handle_redirect_returns_404_for_unknown_code() -> None:
    store = InMemoryCodeStore()

    status, payload = handle_redirect("unknown", store)

    assert status == 404
    assert payload == {"error": "code not found"}


def test_create_app_shorten_route_returns_201_and_code() -> None:
    store = InMemoryCodeStore()
    app = create_app(store)
    body = json.dumps({"long_url": "https://example.com"}).encode("utf-8")

    status, headers, response_body = _call_app(app, "POST", "/shorten", body)

    assert status == "201 Created"
    assert ("Content-Type", "application/json") in headers
    payload = json.loads(response_body)
    assert store.resolve(payload["code"]) == "https://example.com"


def test_create_app_shorten_route_returns_400_for_invalid_url() -> None:
    app = create_app(InMemoryCodeStore())
    body = json.dumps({"long_url": "not-a-url"}).encode("utf-8")

    status, _headers, response_body = _call_app(app, "POST", "/shorten", body)

    assert status == "400 Bad Request"
    assert "error" in json.loads(response_body)


def test_create_app_sets_correct_content_length() -> None:
    app = create_app(InMemoryCodeStore())
    body = json.dumps({"long_url": "https://example.com"}).encode("utf-8")

    _status, headers, response_body = _call_app(app, "POST", "/shorten", body)

    content_length = dict(headers)["Content-Length"]
    assert content_length == str(len(response_body))


def test_create_app_unmatched_route_returns_404() -> None:
    app = create_app(InMemoryCodeStore())

    status, _headers, response_body = _call_app(app, "PUT", "/shorten")

    assert status == "404 Not Found"
    assert json.loads(response_body) == {"error": "not found"}


def test_create_app_root_path_returns_404() -> None:
    app = create_app(InMemoryCodeStore())

    status, _headers, response_body = _call_app(app, "GET", "/")

    assert status == "404 Not Found"
    assert json.loads(response_body) == {"error": "not found"}


def test_create_app_redirect_route_returns_302_with_location() -> None:
    store = InMemoryCodeStore()
    code = store.save("https://example.com")
    app = create_app(store)

    status, headers, response_body = _call_app(app, "GET", f"/{code}")

    assert status == "302 Found"
    assert ("Location", "https://example.com") in headers
    assert dict(headers)["Content-Length"] == "0"
    assert response_body == b""


def test_create_app_redirect_route_returns_404_for_unknown_code() -> None:
    app = create_app(InMemoryCodeStore())

    status, _headers, response_body = _call_app(app, "GET", "/unknown")

    assert status == "404 Not Found"
    assert json.loads(response_body) == {"error": "code not found"}
