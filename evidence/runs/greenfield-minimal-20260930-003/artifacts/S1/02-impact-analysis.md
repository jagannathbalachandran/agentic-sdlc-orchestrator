# Impact Analysis

Scope: FR-1 (shorten), FR-2 (redirect) — see 01-requirements.md.

## Starting state

The repository is a greenfield scaffold with no application logic yet:

- `src/service/__init__.py` — placeholder module, only `__version__`.
- `tests/unit/`, `tests/acceptance/` — empty (`__init__.py` only).
- `pyproject.toml` — `dependencies = []`, `mypy --strict`, `ruff`, coverage
  gate at 85%, `pytest` as test runner.
- `.orchestrator/project.toml` — `approved_dependencies = []`.
- `scripts/check.py` — quality gate: ruff check, ruff format --check, mypy
  --strict, pytest (coverage-gated), pip-audit, run in that order.

There is no existing HTTP layer, routing, storage, or data model to
integrate with — this is new construction inside the scaffold's boundaries,
not a modification of pre-existing behavior.

## Affected / new modules

- `src/service/app.py` (or similar) — HTTP entry point: request dispatch for
  `POST /shorten` and `GET /{code}`.
- `src/service/store.py` (or similar) — in-memory mapping of short code →
  long URL, and code generation/collision handling.
- `src/service/__init__.py` — likely gains exports once real modules exist;
  currently just a version placeholder.
- Possibly `src/service/__main__.py` if the service needs to be runnable
  directly (`python -m service`) — not required by REQ-2 itself, but likely
  needed to make the two endpoints reachable/testable end-to-end.
- `tests/unit/` — new unit tests per implementation task (store logic, code
  generation, request parsing/validation).
- `tests/acceptance/` — one test per FR acceptance criterion (FR-1.AC1–3,
  FR-2.AC1–2).

## API surface

Two new endpoints, both new (no existing API to break):

- `POST /shorten` — request: long URL (body format not yet fixed, e.g. JSON
  `{"url": "..."}`). Response: short code + 2xx on success, 4xx on invalid
  input.
- `GET /{code}` — response: 3xx redirect with `Location` header on hit, 404
  on miss.

No versioning, auth, or other endpoints are in scope per REQ-2.

## Data model

- New, minimal: `code -> long_url` mapping only. No fields beyond what FR-1/
  FR-2 need (no timestamps, hit counts, owners, etc., since REQ-2 doesn't
  ask for them).
- In-memory only (per the Assumptions in 01-requirements.md) — no schema,
  no ORM, no external store.

## Migrations

None. There is no existing database or persisted schema in this scaffold,
so there is nothing to migrate. If persistence is added later, that would
be a new capability outside REQ-2's scope, not a migration of existing data.

## Risks

- **No approved dependency for an HTTP framework.** `approved_dependencies`
  and `pyproject.toml` `dependencies` are both empty. Implementing routing,
  request parsing, and redirects by hand on `http.server` (stdlib) is more
  error-prone than using a framework (edge cases: trailing slashes, method
  mismatches, URL-encoded codes, header casing). If a framework (e.g.
  Flask/FastAPI) turns out to be preferred, that requires a dependency
  approval step before implementation — not assumed here.
- **Concurrency/thread-safety of the in-memory store.** If the chosen HTTP
  server is multi-threaded, the code→URL map and code-generation/collision
  check need to be safe under concurrent requests; a naive dict without
  locking could race on simultaneous `POST /shorten` calls.
- **Coverage gate (85%) and `mypy --strict`.** New modules must be fully
  typed and well-tested from the start; hand-rolled HTTP parsing tends to
  have hard-to-cover branches (malformed requests, partial reads).
- **No persistence means data loss on restart.** Acceptable under the
  stated assumptions, but a risk if any consumer expects short links to
  survive a redeploy — flagged here rather than silently assumed away.
- **Short-code collision strategy is unspecified beyond "distinct codes"**
  (FR-1.AC3); implementation must pick a generation scheme (e.g. random
  base62, incrementing counter) and handle the collision-retry path, which
  is untested surface area if not deliberately covered.
