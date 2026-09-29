# Project conventions for AI-assisted work

- Layering: api → service → repository; no DB access or business logic in route handlers.
- Type hints everywhere; mypy strict must pass.
- Every change ships with tests; a task is not done until `scripts/check.py` passes.
- Stay within the task brief; do not add endpoints, dependencies or features not asked for.
- Never put secrets in code, prompts, logs or commits; configuration via environment variables.
- Prefer small, reviewable changes; state every assumption explicitly.
- Before writing code, list the files to be created/changed and any assumptions, then
  wait for my explicit go-ahead before writing any code.
- New dependencies are added only with explicit approval, and must always include
  a minimum version bound (e.g. `package>=X.Y.Z`).
- All code, including `scripts/`, must pass `ruff` and `mypy --strict`. Never disable
  a rule globally — use a targeted `# noqa` (or equivalent) with a justification comment.
- CI changes must use least-privilege permissions, pin actions to a specific major
  version (e.g. `actions/checkout@v4`), and set `timeout-minutes` on every job.
- Never create or edit AI_LOG.md or docs/transcripts/ — the engineer writes those.

## Code design

- Single responsibility per function/class.
- Functions aim for ≤20 lines and ≤4 parameters; classes aim for ≤200 lines —
  exceed either only with a one-line comment explaining why.
- Inject dependencies (e.g. repositories into services) rather than constructing
  them internally.
- Side effects belong at the edges (API/repository layers); keep core logic pure.
- Raise specific domain exceptions; no bare `except` and no swallowed errors.
- No magic numbers/strings — use named constants.
- Docstrings on public functions/classes; descriptive names throughout.
