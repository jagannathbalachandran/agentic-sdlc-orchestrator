# Requirements

## FR-1: Shorten a long URL
Cites: REQ-2

`POST /shorten` accepts a long URL and returns a short code.

### FR-1.AC1
Given a request body containing a syntactically valid long URL, when `POST /shorten` is called, then the response has a 2xx status and a body containing a short code that was not present in the request.

### FR-1.AC2
Given a request body that is missing the URL field or contains a syntactically invalid URL, when `POST /shorten` is called, then the response has a 4xx status and no short code is generated.

### FR-1.AC3
Given a short code returned by FR-1.AC1, when it is looked up later, then it resolves back to the exact long URL that was submitted (byte-for-byte, no normalization changes).

## FR-2: Redirect from a short code
Cites: REQ-2

`GET /{code}` redirects to the original URL.

### FR-2.AC1
Given a short code previously returned by `POST /shorten`, when `GET /{code}` is called, then the response is an HTTP redirect (3xx) whose `Location` header equals the original long URL.

### FR-2.AC2
Given a code that was never issued by `POST /shorten`, when `GET /{code}` is called, then the response has a 404 status and no `Location` header is set.

## Assumptions
- Short codes are server-generated (not client-supplied) and unique per stored URL; format/length is an implementation detail left open by REQ-2.
- Redirect uses a 3xx status (exact choice of 301 vs 302/307 is an implementation detail); acceptance criteria only require "a redirect."
- Submitting the same long URL twice may produce the same or a different short code — REQ-2 does not require deduplication, so either behavior satisfies FR-1.
- No authentication, rate limiting, expiration, custom aliases, analytics, or URL-safety checks are in scope — REQ-2 explicitly limits the service to "two capabilities only."
- Persistence mechanism (in-memory vs. durable store) is unconstrained by REQ-2; either satisfies the acceptance criteria as stated.

## Open Questions
None blocking — all ambiguities above are resolvable via the stated assumptions without changing observable behavior required by REQ-2.
