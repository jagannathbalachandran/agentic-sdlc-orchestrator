# S7b Review Findings

Scope: `src/service/*.py` and `tests/**` from this run, reviewed against
`02-design.md` (DD-1..DD-4) and `03-plan.md` (T-1.1..T-2.2), with
`01-requirements.md` and `docs/architecture.md` as supporting context.

Overall: the implementation is a close, faithful realization of the design.
`InMemoryCodeStore`/`generate_code` (DD-1), `validate_long_url`/
`handle_shorten` (DD-2), `handle_redirect` (DD-3), and `create_app`'s
routing/response-encoding (DD-4) all match their documented contracts and
endpoint tables, including the 302-with-no-Content-Type / no-body redirect
rule and the uniform JSON error shape. Status/AC traceability (FR-1.AC1-3,
FR-2.AC1-2) is covered by both unit and acceptance tests. No unapproved
dependencies were introduced (`pyproject.toml` `dependencies = []` unchanged),
consistent with the design's "no new dependencies" decision. The findings
below are minor deviations/robustness gaps, not functional breaks.

## finding-1

- **Severity:** low
- **File(s):** `src/service/app.py:76-81` (`_read_body`)
- **Why it matters:** `_read_body` parses `CONTENT_LENGTH` with
  `int(str(environ.get("CONTENT_LENGTH") or 0))` and only guards against a
  non-numeric value (`except ValueError: length = 0`). A negative value
  (e.g. a request with header `Content-Length: -1`) parses successfully as
  `int` and is passed straight to `wsgi_input.read(length)`. For a
  negative argument, `.read()` on a file-like object reads until EOF
  instead of a bounded number of bytes, so a crafted negative
  `Content-Length` causes an unbounded/blocking read against the raw
  socket-backed `wsgi.input` stream (`wsgiref` does not wrap it in a
  length-limiting reader), rather than the bounded read the design implies.
  This is a minor robustness/DoS-adjacent gap, not covered by any test.

## finding-2

- **Severity:** low
- **File(s):** `src/service/app.py:127`
- **Why it matters:** DD-4 and plan task T-2.2 both specify the code is
  derived by "stripping leading `/`" (singular) from `PATH_INFO`. The
  implementation uses `path.lstrip("/")`, which strips *all* leading
  slashes rather than exactly one. For a normal single-slash `PATH_INFO`
  (the only shape `wsgiref`/real WSGI servers produce) this is
  behaviorally identical, so there is no observed functional bug and no
  test exercises the divergent case — but it is a literal deviation from
  the documented DD-4/T-2.2 behavior, so a future PATH_INFO edge case
  (e.g. a path with a doubled slash) would resolve differently than
  specified.

## finding-3

- **Severity:** low
- **File(s):** `src/service/app.py:36-37`, `02-design.md:136`
- **Why it matters:** DD-2 declares `handle_shorten(body: bytes, store:
  CodeStore)`, but the implementation widens the signature to `body: str |
  bytes`. Behaviorally this is a superset (bytes still works, `json.loads`
  natively accepts `str` too) and is exercised by both `bytes` and `str`
  call sites in the test suite, so it isn't a functional defect. It is,
  however, an undocumented deviation from the DD-2 contract as written —
  `docs/architecture.md` and `02-design.md` were not updated to reflect the
  wider accepted type.
