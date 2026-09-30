# Design

## Architectural significance

This change is **architecturally significant**: it introduces the service's
first HTTP component (a Flask app with routing/error handling), its first
data model (a short-code → URL mapping), and its persistence approach
(in-memory store behind a swappable interface). `docs/architecture.md` has
been created to record this.

## Technology stack

- **Language**: Python 3.11+ (per approved greenfield template; matches
  `pyproject.toml` `requires-python = ">=3.11"`).
- **HTTP framework**: [Flask](https://flask.palletsprojects.com/) `>=3.0,<4.0`
  — a new runtime dependency, added to `[project.dependencies]` in
  `pyproject.toml`. Chosen over FastAPI/starlette to keep the dependency
  footprint minimal (no ASGI server, no pydantic) for a two-endpoint service,
  and over raw `wsgiref`/stdlib `http.server` to get routing, a request
  context, and a first-class test client without hand-rolled plumbing.
- **Test client**: `flask.testing.FlaskClient`, obtained via
  `app.test_client()` — ships with Flask, no additional dependency.
- **New dependencies** (to be added to `pyproject.toml`):
  - `flask>=3.0,<4.0` (runtime, under `[project] dependencies`)
- **Existing dev dependencies unchanged**: `pytest>=8.3.0`,
  `pytest-cov>=5.0.0`, `ruff>=0.6.0`, `mypy>=1.11.0`, `pip-audit>=2.7.0`.
- **Persistence**: in-memory (process-local `dict`), wrapped behind a small
  storage interface (`URLStore`) so a durable backend can be substituted
  later without changing route handlers (see DD-3). No database dependency
  is introduced now, consistent with REQ-2's silence on persistence
  (01-requirements.md Assumptions).

## DD-1: Application factory and routing

Cites: FR-1, FR-2

A Flask application factory wires the two required routes to handler
functions in a dedicated module, keeping route I/O (HTTP parsing, status
codes) separate from the storage/generation logic (DD-3).

**Module**: `src/service/app.py`

```python
from flask import Flask

def create_app(store: "URLStore | None" = None) -> Flask:
    """Build and return the configured Flask app.

    If `store` is omitted, a fresh in-memory `URLStore` is created and
    bound to `app.config["URL_STORE"]`. Passing a store explicitly lets
    tests inject a pre-seeded or fake store.
    """
    ...

def register_routes(app: Flask) -> None:
    """Attach POST /shorten and GET /<code> to `app`."""
    ...
```

The factory stores the `URLStore` instance on `app.config["URL_STORE"]`;
handlers retrieve it via `flask.current_app.config["URL_STORE"]` rather than
a module-level global, so multiple `create_app()` calls (e.g. one per test)
do not share state.

## DD-2: `POST /shorten` contract

Cites: FR-1

**Request**

```
POST /shorten
Content-Type: application/json

{"url": "https://example.com/some/long/path?q=1"}
```

**Responses**

| Condition | Status | Body |
|---|---|---|
| `url` present and a syntactically valid absolute HTTP(S) URL | `201 Created` | `{"code": "<short-code>", "url": "<original-url>"}` |
| `url` missing, not a string, or fails validation (no `scheme`/`netloc`, or scheme not `http`/`https`) | `400 Bad Request` | `{"error": "invalid_url"}` |
| Request body is not valid JSON | `400 Bad Request` | `{"error": "invalid_request"}` |

Validation satisfies FR-1.AC2: no short code is generated or stored on the
`400` path. Round-tripping the exact submitted string (FR-1.AC3) is
guaranteed because the store persists the raw `url` value verbatim — no
normalization (trailing-slash stripping, percent-encoding changes, etc.) is
applied.

**Handler signature** (`src/service/app.py`):

```python
def shorten() -> tuple[Response, int]:
    """Handle POST /shorten. Reads JSON body, validates, delegates to
    URLStore.put, and returns (jsonify(...), status)."""
    ...
```

**Validation function** (`src/service/urls.py`):

```python
def is_valid_url(candidate: object) -> bool:
    """True if `candidate` is a str with an http/https scheme and a
    non-empty netloc, per urllib.parse.urlparse."""
    ...
```

## DD-3: Storage and short-code generation

Cites: FR-1, FR-2

A minimal storage interface decouples route handlers from the persistence
mechanism, satisfying the "persistence is an implementation detail" note in
01-requirements.md while keeping today's implementation in-memory.

**Module**: `src/service/storage.py`

```python
class URLStore:
    """In-memory short-code -> URL store. Not thread-safe beyond the GIL;
    acceptable for a single-process minimal service."""

    def __init__(self) -> None:
        self._codes: dict[str, str] = {}

    def put(self, url: str) -> str:
        """Generate a unique short code for `url`, store the mapping, and
        return the code. Retries generation on the (rare) collision."""
        ...

    def get(self, code: str) -> str | None:
        """Return the original URL for `code`, or None if unknown."""
        ...
```

**Module**: `src/service/codes.py`

```python
CODE_ALPHABET: str = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
CODE_LENGTH: int = 7

def generate_code() -> str:
    """Return a random CODE_LENGTH-character string drawn from
    CODE_ALPHABET using `secrets.choice` (not `random`, to avoid
    predictable codes)."""
    ...
```

`URLStore.put` calls `generate_code()` in a loop, re-rolling on collision
(checked via `code in self._codes`) until a free code is found — satisfying
FR-1.AC1's "not present in the request" requirement is trivial since codes
are generated independently of the submitted URL, and uniqueness against
prior stored codes is enforced by the collision check. Duplicate long URLs
are permitted to map to different codes (no dedup), matching the stated
assumption.

## DD-4: `GET /<code>` contract

Cites: FR-2

**Request**

```
GET /{code}
```

**Responses**

| Condition | Status | Headers |
|---|---|---|
| `code` exists in the store | `302 Found` | `Location: <original-url>` |
| `code` does not exist | `404 Not Found` | *(no `Location` header)* |

**Handler signature** (`src/service/app.py`):

```python
def redirect_to_original(code: str) -> Response:
    """Handle GET /<code>. Looks up `code` via URLStore.get; on hit,
    returns flask.redirect(url, code=302); on miss, aborts with 404."""
    ...
```

302 is chosen (over 301) so that re-shortening the same URL later under a
different code, or removing a code, is not permanently cached by clients —
an implementation choice explicitly left open by 01-requirements.md.
