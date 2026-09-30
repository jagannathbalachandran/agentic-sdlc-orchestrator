# Design

Source: 01-requirements.md (FR-1, FR-2), 02-impact-analysis.md.

## Significance decision

This change is **architecturally significant**: it introduces the service's
first components (an HTTP entry point and an in-memory data store), and
establishes the first data model (`code -> long_url`). No such structure
exists yet in the scaffold. `docs/architecture.md` is created (not updated —
it did not previously exist) alongside this document.

## Technology stack

- **Language**: Python 3.11+ (per `pyproject.toml` `requires-python = ">=3.11"`).
- **HTTP framework**: none — stdlib only. `pyproject.toml` declares
  `dependencies = []` and `.orchestrator/project.toml` declares
  `approved_dependencies = []` (per 02-impact-analysis.md), so no third-party
  framework (Flask/FastAPI/etc.) is available without a separate approval
  step. The service is implemented as a stdlib **WSGI application**
  (`environ`/`start_response` callable per PEP 3333) served by
  `wsgiref.simple_server.make_server` from the standard library.
- **Test client**: no new dependency. Unit tests call the WSGI callable
  directly with a hand-built `environ` dict and a `start_response` recorder
  (no sockets). Acceptance tests start the real `wsgiref` server on an
  ephemeral port in a background thread and drive it with `http.client`
  (stdlib) or `urllib.request` (stdlib), asserting on status code, headers
  (`Location`), and body bytes.
- **New dependencies**: none. Everything below uses only the Python 3.11
  standard library (`wsgiref`, `http`, `json`, `re`, `secrets`, `threading`,
  `urllib.parse`, `dataclasses`, `typing`).

If a richer HTTP framework is desired later, that requires a dependency
approval step outside this design (per the risk noted in
02-impact-analysis.md); this design does not assume it.

## DD-1: WSGI HTTP application and routing

Cites: FR-1, FR-2

A single WSGI callable dispatches both endpoints. Routing is a plain method
+ path match; no path templating library is needed for two routes.

```python
# src/service/app.py
from collections.abc import Callable, Iterable
from typing import Any

WSGIEnviron = dict[str, Any]
StartResponse = Callable[[str, list[tuple[str, str]]], None]

class ShortenerApp:
    def __init__(self, store: "URLStore") -> None: ...

    def __call__(
        self, environ: WSGIEnviron, start_response: StartResponse
    ) -> Iterable[bytes]: ...

def create_app(store: "URLStore | None" = None) -> ShortenerApp: ...
```

Dispatch rules inside `__call__`:

| Method | Path pattern | Handler                | Success | Failure |
|--------|---------------|-------------------------|---------|---------|
| POST   | `/shorten`    | `_handle_shorten`       | 201     | 400 (bad body), 404 (any other path) |
| GET    | `/{code}` (`^/[^/]+$`, `code != ""`, `code != "shorten"`) | `_handle_redirect` | 302     | 404 (unknown code or unmatched path) |
| other  | anything else | —                       | —       | 404     |

`code` is extracted via `PATH_INFO[1:]` after confirming it contains no
further `/`. This satisfies FR-1 (routing + response shape for `/shorten`)
and FR-2 (routing + redirect for `/{code}`).

### Response contracts

`POST /shorten`

- Request: `Content-Type: application/json`, body `{"url": "<string>"}`.
- Success (FR-1.AC1, FR-1.AC3): status `201 Created`,
  `Content-Type: application/json`, body `{"code": "<short code>"}`.
- Failure (FR-1.AC2): status `400 Bad Request`,
  `Content-Type: application/json`, body `{"error": "<message>"}`. No entry
  is added to the store (verified via DD-3's `add` never being called on the
  invalid-input path).

`GET /{code}`

- Success (FR-2.AC1): status `302 Found`, header `Location: <original URL>`
  (byte-exact match of the URL originally submitted to `POST /shorten`),
  empty body.
- Failure (FR-2.AC2): status `404 Not Found`, `Content-Type: application/json`,
  body `{"error": "not found"}`.

## DD-2: URL validation for `POST /shorten`

Cites: FR-1

```python
# src/service/validation.py
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
```

Validation steps (all failures raise `ValidationError`, caught in
`app._handle_shorten` and turned into the 400 response from DD-1):

1. `json.loads(raw_body)` — catch `json.JSONDecodeError`.
2. Result must be a `dict` with key `"url"` whose value is a non-empty `str`.
3. `urllib.parse.urlsplit(url)` must yield `scheme in ("http", "https")` and
   a non-empty `netloc`.

## DD-3: In-memory URL store and short-code generation

Cites: FR-1, FR-2

```python
# src/service/store.py
import threading

class URLStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._codes: dict[str, str] = {}

    def add(self, long_url: str) -> str:
        """Generate a fresh, unused code, store code -> long_url, return code.

        Thread-safe: generation + uniqueness check + insert happen under
        self._lock, so concurrent POST /shorten calls (FR-1.AC3) cannot
        observe or produce the same code.
        """

    def get(self, code: str) -> str | None:
        """Return the long URL for code, or None if unknown (FR-2.AC2)."""
```

```python
# src/service/codegen.py
import secrets

_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"

def generate_code(length: int = 7) -> str:
    """Return a random base62 string of the given length using secrets
    (CSPRNG), not random — codes must not be guessable/collidable in
    practice."""
    return "".join(secrets.choice(_ALPHABET) for _ in range(length))
```

`URLStore.add` calls `generate_code()` and re-generates on the (rare)
collision with an existing key, retrying under the same lock acquisition
until a free code is found, before inserting. This directly implements
FR-1.AC1 (non-empty, previously-unused code) and FR-1.AC3 (distinct codes
across calls). `URLStore.get` implements the lookup half of FR-2.AC1 and
FR-2.AC2.

## DD-4: Process entry point

Cites: FR-1, FR-2

```python
# src/service/__main__.py
import os
from wsgiref.simple_server import make_server

def main() -> None:
    """Build the app (DD-1) over a fresh URLStore (DD-3) and serve it via
    wsgiref.simple_server, reading HOST (default "127.0.0.1") and PORT
    (default 8000) from the environment. Blocks in serve_forever()."""
```

This is what makes `POST /shorten` and `GET /{code}` reachable as real HTTP
endpoints (both FRs) for manual use and for acceptance tests that exercise
the service over a real socket via `http.client`/`urllib.request`.

## Data model

Single in-process mapping, owned by `URLStore` (DD-3):

| Field      | Type  | Notes                                   |
|------------|-------|------------------------------------------|
| `code`     | `str` | key; base62, length 7, CSPRNG-generated |
| `long_url` | `str` | value; validated `http`/`https` absolute URL, stored byte-exact for FR-2.AC1 |

No persistence, no additional fields (timestamps, owners, hit counts) — per
the Assumptions in 01-requirements.md and the Data model section of
02-impact-analysis.md.
