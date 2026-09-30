from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from http.client import responses as _HTTP_REASONS
from typing import BinaryIO, cast
from urllib.parse import urlsplit

from service.store import CodeStore

_VALID_SCHEMES = {"http", "https"}

WSGIEnviron = dict[str, object]
StartResponse = Callable[[str, list[tuple[str, str]]], None]


class ValidationError(ValueError):
    """Raised for a malformed or missing long_url."""


def validate_long_url(value: object) -> str:
    """Return value if it is a non-empty http(s) URL string, else raise
    ValidationError."""
    if not isinstance(value, str) or not value:
        raise ValidationError("long_url must be a non-empty string")

    parts = urlsplit(value)
    if parts.scheme not in _VALID_SCHEMES:
        raise ValidationError("long_url must use http or https")
    if not parts.netloc:
        raise ValidationError("long_url must include a host")

    return value


def handle_shorten(
    body: str | bytes, store: CodeStore
) -> tuple[int, dict[str, object]]:
    """Parse a JSON request body, validate its long_url, save it via store,
    and return a (status_code, payload) tuple."""
    try:
        data = json.loads(body)
    except (ValueError, TypeError):
        return 400, {"error": "request body must be valid JSON"}

    if not isinstance(data, dict):
        return 400, {"error": "request body must be a JSON object"}

    try:
        long_url = validate_long_url(data.get("long_url"))
    except ValidationError as exc:
        return 400, {"error": str(exc)}

    code = store.save(long_url)
    return 201, {"code": code}


def handle_redirect(code: str, store: CodeStore) -> tuple[int, dict[str, object]]:
    """Resolve code via store and return a (status_code, payload) tuple:
    (302, {"Location": long_url}) if found, else (404, {"error": ...})."""
    long_url = store.resolve(code)
    if long_url is None:
        return 404, {"error": "code not found"}
    return 302, {"Location": long_url}


def _status_line(status: int) -> str:
    """Return a WSGI status line like '201 Created' for an HTTP status code."""
    return f"{status} {_HTTP_REASONS.get(status, '')}".strip()


def _read_body(environ: WSGIEnviron) -> bytes:
    """Read the raw request body from environ's wsgi.input, using
    CONTENT_LENGTH to bound the read."""
    try:
        length = int(str(environ.get("CONTENT_LENGTH") or 0))
    except ValueError:
        length = 0
    wsgi_input: BinaryIO = environ["wsgi.input"]  # type: ignore[assignment]
    body: bytes = wsgi_input.read(length)
    return body


def _json_response(
    status: int, payload: dict[str, object], start_response: StartResponse
) -> Iterable[bytes]:
    """Encode payload as a JSON WSGI response with the given status code."""
    body = json.dumps(payload).encode("utf-8")
    headers = [
        ("Content-Type", "application/json"),
        ("Content-Length", str(len(body))),
    ]
    start_response(_status_line(status), headers)
    return [body]


def _redirect_response(location: str, start_response: StartResponse) -> Iterable[bytes]:
    """Encode an empty-body 302 WSGI response with a Location header."""
    headers = [
        ("Location", location),
        ("Content-Length", "0"),
    ]
    start_response(_status_line(302), headers)
    return [b""]


def create_app(
    store: CodeStore,
) -> Callable[[WSGIEnviron, StartResponse], Iterable[bytes]]:
    """Build and return a WSGI application closing over store.

    Routes:
      POST /shorten -> handle_shorten
      GET /{code}   -> handle_redirect
      anything else -> (404, {"error": "not found"})
    """

    def app(environ: WSGIEnviron, start_response: StartResponse) -> Iterable[bytes]:
        method = str(environ.get("REQUEST_METHOD", ""))
        path = str(environ.get("PATH_INFO", ""))

        if method == "POST" and path == "/shorten":
            status, payload = handle_shorten(_read_body(environ), store)
            return _json_response(status, payload, start_response)

        if method == "GET" and path not in ("", "/"):
            code = path.lstrip("/")
            status, payload = handle_redirect(code, store)
            if status == 302:
                location = cast(str, payload["Location"])
                return _redirect_response(location, start_response)
            return _json_response(status, payload, start_response)

        return _json_response(404, {"error": "not found"}, start_response)

    return app
