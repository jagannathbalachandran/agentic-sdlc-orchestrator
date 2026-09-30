# Architecture

## Overview

A minimal URL-shortener service (REQ-2). A single WSGI application exposes
two routes and delegates persistence to a pluggable store abstraction.

```
Client
  │
  │ POST /shorten { "long_url": ... }      GET /{code}
  ▼                                          ▼
┌──────────────────────────────────────────────────┐
│  WSGI app (service/app.py: create_app)            │
│    - routes by (method, PATH_INFO)                 │
│    - handle_shorten / handle_redirect               │
└───────────────────────┬────────────────────────────┘
                         │ CodeStore protocol
                         ▼
              ┌────────────────────────┐
              │ InMemoryCodeStore        │
              │ (service/store.py)       │
              │ dict[code -> long_url]   │
              └────────────────────────┘
```

## Components

- **`service/app.py`** — WSGI entry point (`create_app`), request routing,
  request/response translation (JSON parsing/serialization, status codes).
- **`service/store.py`** — `CodeStore` protocol plus `InMemoryCodeStore`,
  the process-local dict-backed implementation, and `generate_code` (base62,
  length 7, `secrets.choice`-based, collision-checked against the store).

## Data model

Single mapping, owned by `CodeStore`: `code: str -> long_url: str`. No
other entities. No persistence beyond process memory (see 02-design.md open
question resolutions for rationale).

## External interfaces

HTTP only, served over WSGI (stdlib `wsgiref`; see 02-design.md's
Technology stack section for why no third-party framework was introduced).

| Route | Method | Purpose |
|---|---|---|
| `/shorten` | POST | Mint a short code for a submitted long URL |
| `/{code}` | GET | Redirect to the long URL for a known code |

## Cross-cutting decisions

- **Persistence:** in-memory only, single process; no restart durability.
  Revisit if a future REQ adds durability, multi-instance deployment, or
  expiry.
- **Error handling:** JSON error bodies (`{"error": "<message>"}`) for every
  non-2xx/3xx response; redirects (302) carry no body, only `Location`.
- **Security:** short codes are generated with `secrets.choice` (not a
  predictable PRNG or sequential counter) to resist enumeration of minted
  codes. No auth/rate-limiting — explicitly out of scope per REQ-2.

## Change log

- 2026-09-30 (FR-1, FR-2 / DD-1..DD-4): initial version — introduced the
  WSGI app, routing, and in-memory `CodeStore`.
