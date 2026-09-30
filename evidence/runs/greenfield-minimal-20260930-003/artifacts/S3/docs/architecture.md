# Architecture

## Overview

A minimal URL-shortener service. Single process, no external dependencies,
no persistence. Built entirely on the Python 3.11 standard library.

```
            WSGI request                    URLStore (in-memory)
Client ───────────────────▶ ShortenerApp ───────────────────────▶ {code: long_url}
       ◀───────────────────  (app.py)    ◀───────────────────────
         201 / 302 / 400 / 404
```

## Components

- **`service.app.ShortenerApp`** (`src/service/app.py`) — WSGI callable.
  Routes `POST /shorten` and `GET /{code}`; translates validation/store
  results into HTTP status codes, headers, and JSON bodies.
- **`service.validation`** (`src/service/validation.py`) — parses and
  validates the `POST /shorten` request body (JSON with an `http`/`https`
  `url` field).
- **`service.codegen`** (`src/service/codegen.py`) — generates random
  base62 short codes via `secrets` (CSPRNG).
- **`service.store.URLStore`** (`src/service/store.py`) — thread-safe
  in-memory `code -> long_url` map; owns code generation/collision retry on
  insert and lookup on read.
- **`service.__main__`** (`src/service/__main__.py`) — process entry point;
  wires a `URLStore` into a `ShortenerApp` and serves it with
  `wsgiref.simple_server`.

## Data model

Single mapping, held in process memory only (lost on restart — see
02-design.md's Data model section for the field list). No database, no
schema, no migrations.

## Technology stack

- Python 3.11+, standard library only (no third-party runtime dependencies;
  `approved_dependencies = []`).
- HTTP: stdlib WSGI (`wsgiref.simple_server`).
- Tests: `pytest`, stdlib `http.client`/`urllib.request` as test clients for
  acceptance tests; direct WSGI-environ calls for unit tests.

## Cross-cutting concerns

- **Concurrency**: `wsgiref.simple_server`'s default server is
  single-threaded; if a threading server is substituted later,
  `URLStore` is already lock-protected. Not currently a hard requirement
  since FR-1.AC3 only requires distinctness across sequential calls, but the
  lock is cheap insurance.
- **Error handling**: all failure paths return structured JSON
  (`{"error": "<message>"}`) with an appropriate 4xx status; no stack traces
  or internal details are leaked to clients.
- **Security**: short codes are generated with `secrets` (CSPRNG), not
  `random`, so they are not practically guessable. No auth is in scope
  (REQ-2 names only the two capabilities).
- **Persistence**: explicitly out of scope; see Assumptions in
  01-requirements.md.

## Decision log

- 2026-09-30 — 02-design.md DD-1..DD-4 — initial architecture: stdlib-only
  WSGI service with an in-memory store, chosen because no HTTP framework is
  an approved dependency yet (see 02-impact-analysis.md risks).
