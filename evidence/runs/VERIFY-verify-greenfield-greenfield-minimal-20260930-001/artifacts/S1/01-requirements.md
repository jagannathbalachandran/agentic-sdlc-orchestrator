# Requirements

Derived from REQ-2 (minimal URL shortener: shorten + redirect).

## Assumptions

- No persistence technology is mandated; an in-process store (e.g. in-memory
  dict) is acceptable for this minimal scope unless a later REQ specifies
  otherwise.
- "Short code" means a compact, URL-safe identifier distinct from the long
  URL; generation strategy (random vs. sequential vs. hash-based) is an
  implementation detail not constrained by REQ-2.
- Only `http://` and `https://` long URLs are in scope for validation; no
  other schemes are explicitly required or excluded by REQ-2.
- Shortening the same long URL twice may return either the same or a new
  code — REQ-2 does not specify de-duplication behavior (see open question).
- No authentication, rate limiting, expiry, or analytics are in scope — REQ-2
  names exactly two capabilities and nothing else.
- The redirect uses a standard HTTP redirect status (3xx); the exact code
  (301 vs 302 vs 307) is not specified (see open question).

## Open Questions

- Should POST /shorten be idempotent for a repeated long URL (same code
  returned) or always mint a new code?
- What HTTP status code should GET /{code} use for the redirect (301, 302,
  307)?
- What HTTP status and body should GET /{code} return when the code is
  unknown (404 assumed, but response body/shape is unspecified)?
- What is the expected short-code alphabet/length, if any constraint exists?
- Is long-URL validation (well-formedness, scheme allow-list) required, and
  what error response should invalid input produce?
- Does the store need to survive process restarts, or is in-memory
  acceptable for this scope?

## FR-1: Shorten a long URL via POST /shorten

Cites: REQ-2

A client can submit a long URL to `POST /shorten` and receive a short code
that can later be used to retrieve the original URL.

### FR-1.AC1

Given a valid long URL (e.g. `https://example.com/some/path`) submitted as
the request body to `POST /shorten`, when the request is processed, then the
response has a success status (2xx) and includes a short code that is
non-empty and distinct from the submitted long URL.

### FR-1.AC2

Given two separate `POST /shorten` requests with different long URLs, when
both are processed successfully, then the two returned short codes are
different from each other.

### FR-1.AC3

Given a `POST /shorten` request whose body is missing a long URL (empty or
absent), when the request is processed, then the response has a client
error status (4xx) and no short code is created.

## FR-2: Redirect via GET /{code}

Cites: REQ-2

A client can issue `GET /{code}` using a short code previously returned by
`POST /shorten` and be redirected to the original long URL.

### FR-2.AC1

Given a short code previously returned by a successful `POST /shorten` call
for long URL `U`, when a client sends `GET /{code}`, then the response is an
HTTP redirect (3xx) whose `Location` header equals `U`.

### FR-2.AC2

Given a code that was never returned by `POST /shorten`, when a client sends
`GET /{code}`, then the response has a 404 status and no redirect occurs.
