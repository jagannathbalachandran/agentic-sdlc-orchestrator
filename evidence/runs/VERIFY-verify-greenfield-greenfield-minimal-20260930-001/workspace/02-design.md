# Design

Source: 01-requirements.md (FR-1, FR-2). No 02-impact-analysis.md exists —
this is a greenfield service (scaffold only, `src/service/__init__.py`
exposes just `__version__`), so S2 impact analysis was not produced and does
not apply.

## Significance decision

This change **is architecturally significant**: it introduces the service's
first real component (an HTTP API), its first data model (the short-code →
long-URL mapping), and its first cross-cutting decisions (in-process
persistence strategy, HTTP error-handling contract). `docs/architecture.md`
did not exist and has been created by this stage to record it.

## Technology stack

- **Language:** Python 3.11+ (per `pyproject.toml` `requires-python = ">=3.11"`)
- **HTTP framework:** Python standard library `wsgiref` (PEP 3333 WSGI). No
  third-party web framework is introduced. `pyproject.toml` currently
  declares `dependencies = []` and `.orchestrator/project.toml` declares
  `approved_dependencies = []`; adding a framework (Flask/FastAPI/etc.)
  would require an approval step outside this stage's scope, and the
  service's needs (two routes, no middleware, no templating) do not warrant
  one. The WSGI app is a plain callable (`environ, start_response`), runnable
  either embedded in tests or served via `wsgiref.simple_server.make_server`
  for real HTTP.
- **Test client:** For unit tests, the WSGI app callable is invoked directly
  (no socket) using `wsgiref.util.setup_testing_defaults` to build the
  `environ` — standard library only, no test-client dependency needed. For
  acceptance tests that must observe real HTTP semantics (status line,
  headers, `Location`), `wsgiref.simple_server.make_server` is started on an
  ephemeral port in a background thread and exercised with
  `urllib.request`/`http.client` (standard library).
- **New dependencies:** none. Everything above is standard library, so no
  changes to `pyproject.toml` `dependencies` or `.orchestrator/project.toml`
  `approved_dependencies` are required.

## Open-question resolutions

These resolve 01-requirements.md's "Open Questions" so the contracts below
are unambiguous:

- **Idempotency (FR-1):** `POST /shorten` always mints a new code, even for
  a previously-seen long URL. Simplest behavior consistent with FR-1.AC2;
  avoids a reverse-lookup index the requirements don't ask for.
- **Redirect status (FR-2):** `302 Found`. Short URLs are meant to remain
  redirectable indefinitely and per-request; a permanent `301` risks
  browser/proxy caching that would defeat future extensibility (e.g. code
  reassignment), and `307` offers no benefit here since redirects are always
  `GET`.
- **404 body (FR-2.AC2):** `{"error": "code not found"}`, `Content-Type:
  application/json`, matching the error shape used for FR-1's 400s.
- **Short-code alphabet/length:** base62 (`[A-Za-z0-9]`), fixed length 7,
  giving 62^7 ≈ 3.5×10^12 possible codes. Generated with `secrets.choice`
  (cryptographically unpredictable, avoids enumeration) and re-rolled on
  collision against the current store.
- **Long-URL validation:** required. A submitted value must be a non-empty
  string, parse via `urllib.parse.urlsplit`, and have `scheme` in
  `{"http", "https"}` with a non-empty `netloc`. Anything else (missing,
  empty, unparsable, wrong scheme) is a 400, satisfying FR-1.AC3 and the
  requirements' scheme-scope assumption.
- **Store durability:** in-memory only (a plain `dict`, process lifetime),
  per the requirements' explicit assumption. No filesystem/DB persistence.

## DD-1: In-memory short-code store

Cites: FR-1, FR-2

A single store object owns the code → URL mapping and code generation,
shared by both route handlers. Module: `src/service/store.py`.

```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


class CodeStore(Protocol):
    def save(self, long_url: str) -> str:
        """Mint a new short code for long_url, store the mapping, return the code."""
        ...

    def resolve(self, code: str) -> str | None:
        """Return the long URL for code, or None if code is unknown."""
        ...


@dataclass
class InMemoryCodeStore:
    """CodeStore backed by a process-local dict. Not thread-safe across
    multiple WSGI worker threads sharing one instance beyond the GIL's
    per-bytecode-op atomicity; acceptable for this minimal, single-process
    scope."""

    _codes: dict[str, str] = field(default_factory=dict)
    _code_length: int = 7

    def save(self, long_url: str) -> str: ...
    def resolve(self, code: str) -> str | None: ...


def generate_code(length: int = 7) -> str:
    """Return a random base62 string of the given length using secrets.choice."""
    ...
```

`InMemoryCodeStore.save` calls `generate_code`, re-rolling while the result
collides with an existing key in `_codes`, then stores and returns it.

## DD-2: `POST /shorten` handler

Cites: FR-1

Module: `src/service/app.py`. Request body is JSON: `{"long_url": "<string>"}`.

```python
from __future__ import annotations

from urllib.parse import urlsplit

from service.store import CodeStore


class ValidationError(ValueError):
    """Raised for a malformed or missing long_url."""


def validate_long_url(value: object) -> str:
    """Return value if it is a non-empty http(s) URL string, else raise
    ValidationError."""
    ...


def handle_shorten(body: bytes, store: CodeStore) -> tuple[int, dict[str, str]]:
    """Parse the JSON request body, validate long_url, save it via store,
    and return (status_code, response_json_dict).

    Returns (201, {"code": <code>}) on success.
    Returns (400, {"error": <message>}) if the body is not valid JSON, is
    missing long_url, or long_url fails validate_long_url.
    """
    ...
```

**Endpoint contract**

| | |
|---|---|
| Method/path | `POST /shorten` |
| Request headers | `Content-Type: application/json` |
| Request body | `{"long_url": "https://example.com/some/path"}` |
| Success | `201 Created`, `Content-Type: application/json`, body `{"code": "aZ3kQ9p"}` |
| Validation failure | `400 Bad Request`, `Content-Type: application/json`, body `{"error": "<reason>"}` |

Satisfies FR-1.AC1 (2xx + non-empty code distinct from input — code is a
generated base62 string, never equal to the submitted URL), FR-1.AC2
(`generate_code` collision-avoidance plus independent minting per call gives
distinct codes across calls), and FR-1.AC3 (missing/empty `long_url` →
`ValidationError` → 400, nothing saved to the store).

## DD-3: `GET /{code}` handler

Cites: FR-2

Module: `src/service/app.py`.

```python
def handle_redirect(code: str, store: CodeStore) -> tuple[int, dict[str, str]]:
    """Look up code via store.resolve.

    Returns (302, {"Location": <long_url>}) on success — the caller writes
    this as a redirect response with an empty body.
    Returns (404, {"error": "code not found"}) if code is unknown.
    """
    ...
```

**Endpoint contract**

| | |
|---|---|
| Method/path | `GET /{code}` |
| Success | `302 Found`, `Location: <original long URL>`, empty body |
| Unknown code | `404 Not Found`, `Content-Type: application/json`, body `{"error": "code not found"}` |

Satisfies FR-2.AC1 (302 with `Location` equal to the stored long URL for a
known code) and FR-2.AC2 (404, no `Location` header, for an unrecognized
code).

## DD-4: WSGI wiring and routing

Cites: FR-1, FR-2

Module: `src/service/app.py`. A single WSGI callable dispatches both routes
by method and path, translating the `(status, dict)` tuples from DD-2/DD-3
into WSGI responses.

```python
from __future__ import annotations

from collections.abc import Callable, Iterable

WSGIEnviron = dict[str, object]
StartResponse = Callable[[str, list[tuple[str, str]]], None]


def create_app(
    store: CodeStore,
) -> Callable[[WSGIEnviron, StartResponse], Iterable[bytes]]:
    """Build and return a WSGI application closing over store.

    Routes:
      POST /shorten -> handle_shorten
      GET /{code}   -> handle_redirect (code = PATH_INFO with leading '/' stripped)
      anything else -> (404, {"error": "not found"})
    """
    ...
```

Response encoding rules (applied uniformly for both routes):

- JSON bodies are serialized with `json.dumps(...).encode("utf-8")`.
- `handle_redirect`'s success tuple is rendered as `start_response("302
  Found", [("Location", url), ("Content-Length", "0")])` with an empty body
  (no JSON on success, since redirects carry no payload).
- All other responses set `Content-Type: application/json` and a correct
  `Content-Length`.

`create_app` is the seam tests use: `create_app(InMemoryCodeStore())`
invoked directly in unit tests via `wsgiref.util.setup_testing_defaults`, or
served with `wsgiref.simple_server.make_server("127.0.0.1", 0, app)` for
acceptance tests that need real socket/HTTP behavior.

## Traceability

| FR | DDs |
|---|---|
| FR-1 | DD-1, DD-2, DD-4 |
| FR-2 | DD-1, DD-3, DD-4 |
