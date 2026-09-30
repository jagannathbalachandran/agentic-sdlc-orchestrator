# Implementation Plan

Derived from 02-design.md (DD-1..DD-4), grouped by 01-requirements.md's FRs.

## FR-1

- T-1.1 (DD-1): Implement `InMemoryCodeStore`, `CodeStore` protocol, and `generate_code` (base62, length 7, `secrets.choice`, collision re-roll) in `src/service/store.py`. No dependencies.
- T-1.2 (DD-2): Implement `ValidationError` and `validate_long_url` (non-empty string, `urlsplit`-parsed, scheme in `{http, https}`, non-empty netloc) in `src/service/app.py`. No dependencies.
- T-1.3 (DD-2): Implement `handle_shorten` (parse JSON body, call `validate_long_url`, call `store.save`, return `(201, {"code": ...})` or `(400, {"error": ...})`) in `src/service/app.py`. Depends on T-1.1 (CodeStore/InMemoryCodeStore) and T-1.2 (validate_long_url).
- T-1.4 (DD-4): Implement `create_app` WSGI callable in `src/service/app.py` with routing skeleton, JSON body/response encoding helpers, and the `POST /shorten` route wired to `handle_shorten`. Depends on T-1.3.

## FR-2

- T-2.1 (DD-3): Implement `handle_redirect` (call `store.resolve`, return `(302, {"Location": ...})` or `(404, {"error": "code not found"})`) in `src/service/app.py`. Depends on T-1.1 (CodeStore/InMemoryCodeStore).
- T-2.2 (DD-4): Extend `create_app` in `src/service/app.py` to wire `GET /{code}` to `handle_redirect` (stripping leading `/` from `PATH_INFO` for the code), render the 302 success case as an empty-body redirect with `Location`/`Content-Length` headers, and add the catch-all `(404, {"error": "not found"})` fallback for unmatched routes. Depends on T-1.4 (routing skeleton/response encoding) and T-2.1 (handle_redirect).
