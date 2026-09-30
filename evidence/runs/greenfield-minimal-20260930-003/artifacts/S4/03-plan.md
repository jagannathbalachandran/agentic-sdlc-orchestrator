# Plan

Source: 01-requirements.md (FR-1, FR-2), 02-design.md (DD-1..DD-4).

## FR-1: Shorten a long URL

- T-1.1 (DD-2): Implement request-body validation for `POST /shorten` —
  `ValidationError` and `parse_shorten_body(raw_body)` in
  `src/service/validation.py`, covering JSON parse failure, missing/empty/
  non-string `url`, and non-`http`/`https` scheme (FR-1.AC2). No dependency
  on other tasks.
- T-1.2 (DD-3): Implement CSPRNG short-code generation —
  `generate_code(length=7)` in `src/service/codegen.py` using
  `secrets.choice` over a base62 alphabet. No dependency on other tasks.
- T-1.3 (DD-3): Implement the thread-safe in-memory `URLStore` in
  `src/service/store.py` — `add(long_url) -> str` (generates via
  `generate_code`, retries on collision, inserts under a lock) and
  `get(code) -> str | None`. Depends on T-1.2 (uses `generate_code`).
- T-1.4 (DD-1): Implement `ShortenerApp` in `src/service/app.py` — the WSGI
  `__call__` dispatch table and the `_handle_shorten` handler for
  `POST /shorten`, returning `201` with `{"code": ...}` on success
  (FR-1.AC1, FR-1.AC3) or `400` with `{"error": ...}` on validation failure
  (FR-1.AC2). Depends on T-1.1 (body validation) and T-1.3 (`URLStore.add`).

## FR-2: Redirect from a short code

- T-2.1 (DD-1): Implement the `_handle_redirect` handler in
  `src/service/app.py` for `GET /{code}` — `302` with an exact-match
  `Location` header on a known code (FR-2.AC1), `404` with
  `{"error": "not found"}` for an unknown code or unmatched path
  (FR-2.AC2). Depends on T-1.3 (`URLStore.get`) and T-1.4 (shares the
  routing dispatch table and module established in `app.py`).
- T-2.2 (DD-4): Implement the process entry point `src/service/__main__.py`
  — `main()` wires a fresh `URLStore` (DD-3) into `create_app` (DD-1) and
  serves it via `wsgiref.simple_server.make_server`, reading `HOST`/`PORT`
  from the environment, making both `POST /shorten` and `GET /{code}`
  reachable over a real socket. Depends on T-1.4 and T-2.1 (both handlers
  must exist before the app can be served end-to-end).
