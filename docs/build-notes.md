# Build notes

Short per-task log: what changed, ACs covered, anything deferred or assumed. One
entry per task from `docs/tasks.md`, in build order.

## P0 — `claude -p` feasibility spike

**What changed:** ran 4 live `claude -p` calls against a scratch git repo
(`/tmp/spike-target`) via a Python driver with `subprocess` timeouts, per
`docs/tasks.md` P0's constraints. No orchestrator code touched. Output:
`docs/spikes/claude-p-feasibility.md`.

**Covered:** validates O-4, O-6, O-10 (`docs/architecture-proposal.md` §2).

**Findings / deferred / assumed:**
- O-4 upgraded **Assumed → Verified**: tool-based write + small JSON summary worked
  exactly as designed, first attempt.
- O-6 **stays partially Assumed, recommendation changed**: `--add-dir` alone does
  **not** confine writes (a live test wrote outside it without any denial);
  `--restricted` does block it, but the observed refusal looked like model judgment,
  not a confirmed hard technical denial (`permission_denials` stayed empty). The
  post-stage diff+hash check remains the real enforcement point, unchanged.
- O-10 upgraded **Assumed → Verified at the mechanism level**: `--append-system-prompt`
  accepted without error; persona-fidelity itself not isolated (ordinary prompt
  iteration during T4.2, not a blocker).
- **Constraint deviation:** the reviewer's constraint said "cap with `--max-turns`" —
  no such flag exists in `claude` 2.1.268. Used `--max-budget-usd` + the subprocess
  `timeout` instead. Flagged for review at hard stop (a).
- `architecture-proposal.md`'s O-4/O-6/O-10 status paragraphs updated in place to
  point at the spike doc.

**Hard-stop-(a) review follow-ups (same Task: P0):**
- ADR-001 + T4.2: developer/test-engineer profiles get a scoped Bash limited to
  running pytest (named via `--tools` under `--restricted`); every other role gets
  no Bash.
- ADR-001 + T4.1: per-call timeout now kills the whole process tree (Windows:
  `taskkill /T /F`; POSIX: own process group), not just the direct child. T4.1's DoD
  gained a live timeout test.
- Spike doc + a new `docs/spikes/spike_results.redacted.json` had the local username
  redacted to `<user>` before committing.
- architecture-proposal.md §4.3 gained two more limitations: central audit-repo
  publishing (already SHOULD per requirements rev 2 D-20, not a new trim) and
  workspace confinement's CLI flags not being a hard boundary (ADR-001). T12.3's DoD
  now also requires every SHOULD/COULD item from requirements.md §2.

## T1.1 — Domain models

**What changed:** added `src/orchestrator/models/` with `_patterns.py` (shared ID
regexes) and `run.py`, `graph.py`, `traceability.py`, `decisions.py`, `approvals.py`,
`events.py`, `agent_io.py` — pydantic models for every run-record artifact
(`docs/requirements.md` §11) plus the stage-graph and agent-call shapes
(`docs/architecture-proposal.md` §3.3). 30 unit tests under `tests/unit/models/`,
one file per model module: minimal-valid-input, required-field, and ID-format
invalid-input cases for each. 100% coverage on the new code.

**Covered:** C2-AC2 (scenario snapshot/hash shape); groundwork for C5 (schema gate)
and C12-AC1 (event structure).

**Deferred / assumed:**
- Config schema models (defaults/project/scenario) intentionally live in `config/
  schema.py` (T1.2), not here — `architecture-proposal.md` §3.1's module tree already
  separates them from `models/`; T1.1's own file list agrees, only its prose summary
  was loosely worded.
- Timestamps are required fields everywhere (no `default_factory=datetime.now`
  inside any model) — keeps domain models pure per CLAUDE.md; the caller (engine/
  audit layer) is responsible for stamping the time, once a clock is injected there.
- `Event.injected` is a first-class field (not buried in `payload`) specifically so
  G-16's fault-injection events are trivially queryable.

## T1.2 — Config loader + `validate` (schema errors only)

**What changed:** `src/orchestrator/config/{schema,loader,validate}.py`,
`src/orchestrator/exceptions.py` (`ConfigValidationError`,
`ProjectNotRegisteredError`), `src/orchestrator/cli/commands/validate.py`, and the
top-level `config/defaults.toml` with real Phase-1 default values (coverage 85%;
G-6's limits: 180min run duration, 60 agent calls, 600s per-call timeout, 400-line/
15-file diff-size limit; the 3 retry counts from C9; protected-path globs and
in-house secret-scan regexes for G-4/G-5/G-7). 13 new tests across
`tests/unit/config/` and `tests/unit/cli/commands/`. 100% coverage.

**Covered:** C1-AC1 (schema errors reported before any run — literal scope, no
hardening-merge logic); C2-AC1/AC3 (unregistered-project and invalid-config runs are
rejected).

**Deferred / assumed:**
- `ProjectLookup` is an injected `Callable[[str], str | None]`, not a call into the
  real file-backed registry — the registry itself is T2.2's job. Tests use stub
  lookups; T2.3 wires the real one in. This keeps `config/validate.py` free of a
  forward dependency on a module that doesn't exist yet.
- `cli/commands/validate.py` takes explicit `--defaults`/`--project-config`/
  `--scenario-config` paths rather than resolving them from `ORCH_HOME`/a cloned
  target repo — that resolution logic belongs to the workspace manager (T2.2) and
  the CLI entry point (T2.3), not to this command in isolation.
- `config/defaults.toml`'s `secret_scan_patterns` and `protected_path_globs` are
  real, usable defaults, but the *policy classes* that consume them (T6.2) don't
  exist yet — this task only had to get the config schema and values right.

## T1.3 — Hash-chained event log + atomic run-record I/O

**What changed:** `src/orchestrator/audit/{event_log,run_record}.py`; added
`RunRecordError` to `exceptions.py`. Split `models/events.py`'s `Event` into
`EventDraft` (content, no chain position) + `Event` (adds sequence/prev_hash/hash) —
a small refactor of T1.1's file, needed to keep `EventLog.append`/`_compute_hash`
under the project's 5-arg limit (PLR0913) without losing type safety. 19 new tests
across `tests/unit/audit/`. 100% coverage.

**Covered:** C12-AC1 (every event has run/stage/attempt/agent-call correlation
IDs); C12-AC2 (chain verification detects tamper/deletion — tested directly:
editing a field after the fact, and removing a whole event, both flip `verify()` to
`False`).

**Deferred / assumed:**
- `EventLog` is constructed fresh per process (per the stateless pause/resume
  design, §3.2.1) — it reads the file's last line on `__init__` to pick up
  `sequence`/`prev_hash` where a prior process left off. Within one process, its
  internal lock is the serialization point two parallel stage threads (T6.1) will
  share.
- The interrupted-write test for `run_record.py` fails serialization itself (via a
  test double whose `model_dump_json` raises), not the OS-level write call — this
  covers the property DoD asks for (original file never corrupted) without
  depending on OS-specific fault injection.

## T1.4 — Executor protocol + mock executor

**What changed:** `src/orchestrator/executors/{base,mock}.py`; a generic fallback
fixture at `fixtures/mock/_generic/S1.json`. `AgentCallRequest` (T1.1) gained
`scenario_id: str` and `attempt: int = 1` — needed for O-8's `(scenario_id, stage,
attempt)` fixture key, and equally useful for the real executor's own
logging/correlation later, so they live on the shared request rather than being
mock-only. 9 new tests. 98.67% overall coverage (`executors/base.py` is a pure
`Protocol`, never executed — its 0% is expected, not a gap).

**Covered:** C8-AC1 (engine depends only on the `Executor` protocol); C1-AC3
(`--mock` can run without Claude or the network — the executor itself makes no
network calls); groundwork for §13's mock-required-for-tests NFR.

**Deferred / assumed:**
- Fixture filename lookup tries `<stage>-<attempt>.json` first, then (attempt 1
  only) bare `<stage>.json` — matches architecture-proposal.md O-8's
  `<stage>[-<attempt>].json` notation, read as "the attempt suffix is optional for
  the first attempt."
- Only one generic fallback fixture exists so far (S1). More stages get generic
  fixtures if/when a later task's tests need the mock executor to succeed for them
  without a real scenario fixture; not front-loaded speculatively.

