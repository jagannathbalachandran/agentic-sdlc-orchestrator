# Requirements

Source: REQ-2 (00-source.md / scenario prompt)

> Build a minimal URL shortener with two capabilities only:
> - Shorten: POST /shorten accepts a long URL and returns a short code.
> - Redirect: GET /{code} redirects to the original URL.

## FR-1: Shorten a long URL
Cites: REQ-2

`POST /shorten` accepts a long URL and returns a short code that can later be
used to redirect to that URL.

### FR-1.AC1
Given a request body containing a valid absolute URL (scheme `http` or
`https`), when `POST /shorten` is called, then the response has a 2xx status
and a body containing a short code that is non-empty and did not previously
exist.

### FR-1.AC2
Given a request body containing a missing, empty, or malformed URL (no
scheme, unparsable, or not `http`/`https`), when `POST /shorten` is called,
then the response has a 4xx status and no short code is created.

### FR-1.AC3
Given two separate `POST /shorten` calls (with the same or different long
URLs), when both succeed, then each returns a distinct short code.

## FR-2: Redirect from a short code
Cites: REQ-2

`GET /{code}` redirects the caller to the original long URL previously
registered for `code` via FR-1.

### FR-2.AC1
Given a short code previously returned by a successful `POST /shorten` for
long URL `U`, when `GET /{code}` is called, then the response is an HTTP
redirect (3xx) whose `Location` header equals `U` exactly.

### FR-2.AC2
Given a code that was never returned by `POST /shorten`, when `GET /{code}`
is called, then the response has a 404 status.

## Assumptions

- Storage is in-memory for the lifetime of the running process; REQ-2 does
  not ask for persistence across restarts, and nothing else in scope implies
  a durable store.
- Each successful `POST /shorten` call mints a new code, even if the same
  long URL was submitted before (no deduplication is required by REQ-2).
- Short codes are server-generated (the caller does not choose the code).
- Only `http`/`https` absolute URLs are accepted as "a long URL"; scheme-less
  or relative input is rejected as malformed.
- The response body for `POST /shorten` need only carry the short code
  (e.g. `{"code": "..."}`); REQ-2 does not require the full short URL to be
  echoed back.
- No authentication/authorization is in scope — REQ-2 names only the two
  capabilities.
- `.orchestrator/project.toml` currently sets `approved_dependencies = []`
  and `pyproject.toml` has `dependencies = []`; the implementation is
  assumed to be buildable on the Python 3.11 standard library alone (e.g.
  `http.server`) unless a dependency is separately approved. This does not
  block requirements definition but is carried into the impact analysis as
  a risk.

## Open questions

- None blocking — see Assumptions above for the defaults used to keep FR-1
  and FR-2 testable without further input.
