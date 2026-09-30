# Architecture

## Overview

A minimal URL-shortener service with two HTTP endpoints, built on Flask and
running as a single process with in-memory storage. See `02-design.md` for
per-endpoint contracts (DD-1..DD-4).

```
Client
  |
  | POST /shorten {"url": ...}  ->  201 {"code": ..., "url": ...} | 400
  | GET  /<code>                ->  302 Location: <url>           | 404
  v
Flask app (src/service/app.py)
  - route handlers: shorten(), redirect_to_original()
  - validation: urls.is_valid_url()
  v
URLStore (src/service/storage.py)
  - in-memory dict: code -> url
  - code generation: codes.generate_code() (secrets-based, collision-checked)
```

## Components

- **`service/app.py`** — Flask application factory (`create_app`) and the
  two route handlers. Owns HTTP concerns: request parsing, status codes,
  JSON responses, redirects.
- **`service/urls.py`** — URL validation (`is_valid_url`), independent of
  Flask so it is unit-testable in isolation.
- **`service/codes.py`** — Short-code generation (`generate_code`), using
  `secrets.choice` for non-predictable codes.
- **`service/storage.py`** — `URLStore`, an in-memory mapping of short code
  to original URL, with collision-safe insertion (`put`) and lookup
  (`get`). Isolated behind a small interface so a durable backend can
  replace it later without touching route handlers.

## Data model

Single entity, `URLStore` internal state:

| Field | Type | Notes |
|---|---|---|
| `code` | `str`, length 7, alphabet `[A-Za-z0-9]` | Primary key; server-generated, collision-checked |
| `url` | `str` | Stored verbatim, no normalization; the original submitted value |

No relational schema, no migrations — this is the service's first data
model (see 02-impact-analysis.md: greenfield, no prior schema).

## Persistence

In-memory (`dict`), process-local, non-durable: data is lost on restart.
This is an explicit, documented choice (01-requirements.md Assumptions:
"Persistence mechanism ... is unconstrained by REQ-2"). If durability
becomes a requirement later, `URLStore` is the single seam to swap for a
database-backed implementation — route handlers depend only on its
`put`/`get` interface.

## Cross-cutting concerns

- **Error handling**: invalid input on `POST /shorten` returns `400` with a
  JSON `{"error": "<reason>"}` body; unknown codes on `GET /<code>` return
  `404` with no body requirement. No 5xx-handling strategy beyond Flask's
  default is introduced, since there is no I/O (database, network calls)
  that can fail independently of input validation.
- **Security**: short codes are generated with `secrets.choice` (not
  `random`) to avoid predictable/guessable codes, even though no
  authentication or rate limiting is in scope (01-requirements.md
  Assumptions).
- **Concurrency**: single-process, relies on the GIL for `dict` safety;
  no locking is introduced. Acceptable for a minimal, unscaled service.

## External integrations

None. No outbound network calls, no third-party services.

## Out of scope (per 01-requirements.md)

Authentication, rate limiting, expiration, custom aliases, analytics,
URL-safety checks, deduplication of identical submitted URLs.
