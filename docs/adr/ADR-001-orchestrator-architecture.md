# ADR-001: Orchestrator core architecture

**Status:** Accepted
**Date:** 2026-09-29
**Decider:** Jaggu (reviewed spike findings and all decisions; amendments: scoped pytest Bash for developer/test-engineer, process-tree kill on timeout)

This ADR records the architectural decisions for the Phase 1 vertical slice — the
condensed decision record. Full reasoning, trade-offs, and gap analysis live in
`docs/architecture-proposal.md`; the requirement source of truth is
`docs/requirements.md`; the concrete build order is `docs/tasks.md`; the CLI-behavior
evidence behind the executor decisions is `docs/spikes/claude-p-feasibility.md`.

## Context

The orchestrator drives a target project's SDLC through a fixed, nine-stage graph
(S0–S8, `docs/requirements.md` §7) using AI agents behind an explicit governance
layer — gates, policies, approval checkpoints, bounded retries/rollback, and a
hash-chained audit log — while remaining independent of how agents are actually
executed. `docs/requirements.md` fixes the run-record file formats, the stage graph
structure, and the traceability model as DECIDED; ten items were left open for this
proposal (§17, O-1–O-10). The reviewer subsequently revised scope (D-19) to a ~12–13h
vertical slice that must reach the real executor and all three showcase scenarios,
not stop at a mock-only skeleton.

## Decision

### Engine

- **Custom lightweight engine**, not LangGraph (O-1). The stage graph is static and
  global (`docs/requirements.md` §7), and the run-record persistence format is
  already fixed by §11 — a generic graph-execution library would mean reconciling
  its own checkpointing model against that mandated format, for no benefit at this
  scale. The graph is a static list of `StageSpec`s; a `StageRunner` drives each one
  (entry gate → execute → exit gate → policies → event → commit); `engine.fsm.drive()`
  is the single entry point every run-touching CLI command re-enters.
- **Pause/resume is stateless across process boundaries.** Every CLI invocation is a
  separate process; there is no long-running orchestrator process. `drive()` rebuilds
  all state from `run.json`/`graph.json` on disk on every call — "pause" is a process
  exit while state says `awaiting_approval`; "resume" is reloading state and
  re-entering the same driver. The project lock is a PID + timestamp file, reclaimable
  if the PID is dead or the lock has outlived `max_run_duration`.
- **Parallel stages (S5, S7) run as two threads**, not asyncio or a process pool
  (O-5) — `claude -p` calls are blocking subprocesses that mostly wait, and
  `subprocess.run` releases the GIL while waiting, so two blocking calls overlap
  naturally with no async infrastructure needed elsewhere in an otherwise synchronous
  CLI. **Only the wait on the external call is concurrent** — every side effect the
  orchestrator performs in response (git commit, event-log append, run-record update)
  is serialized through one lock per run, so the two branches never race on the
  shared working tree or the hash chain, even though their file edits are already
  disjoint by path partitioning.

### Storage and config

- **Flat files only** (JSON/JSONL), no SQLite (O-2) — `docs/requirements.md` §11
  already fixes the run-record format; a derived cache isn't worth a second source of
  truth at this scale (one engineer, a handful of runs per demo).
- **TOML (stdlib `tomllib`) for every human-authored config**; **JSON** for the one
  machine-written artifact (`config.effective.json`), avoiding a TOML writer entirely
  (O-3). Zero new dependencies.

### Agent execution

- **Agents write their deliverables directly into the workspace via their own tools**
  (Write/Edit, and a role-scoped Bash where granted — see below), returning only a
  small JSON summary (`produced_ids`, `files_written`) — not a fenced-JSON-in-response
  payload (O-4, revised by reviewer). Gates read the actual files off disk.
  **Verified** by the P0 spike: a live call wrote its file exactly where instructed
  and returned the requested summary shape verbatim, first attempt.
- **Workspace confinement is `--restricted --add-dir <workspace> --allowedTools
  <profile list>` as a preventive layer, plus the mandatory post-stage filesystem
  diff+hash check** (O-6) — the post-stage check is the actual, non-negotiable
  enforcement point (`docs/requirements.md` C6 names it explicitly). The P0 spike
  found `--add-dir` alone gives **no** real boundary (a live write outside it
  succeeded); `--restricted` did block the same write, but the observed refusal
  looked like model judgment rather than a confirmed hard denial — treated as
  reducing how often the post-stage check has to catch something, not as a
  substitute for it.
- **Bash is role-scoped, not blanket-available.** Under `--restricted`, Bash and
  other code-execution tools are removed by default unless named via `--tools`.
  **Developer and test-engineer profiles get Bash re-enabled, scoped to running
  pytest only** (named via `--tools` under `--restricted`, allowlisted narrowly as
  `Bash(python -m pytest *)` — not bare `Bash(pytest *)`, which would never match
  since this repo's own `scripts/check.py` and target repos alike invoke tests via
  `python -m pytest`, never bare `pytest`); every other role (analyst, architect,
  planner, technical writer, reviewer) gets no Bash at all. This is a
  least-privilege narrowing on top of the
  confinement above, not a substitute for it — the post-stage diff check still
  enforces file confinement regardless of which tools a call used.
- **Profiles render into a system prompt + CLI flags**, not Claude Code
  subagent/skill files (O-10) — keeps the executor interface
  (`execute(profile, inputs) -> response`) free of Claude-Code-specific filesystem
  side effects, and keeps mock-fixture replay simple (a fixture is just
  (rendered prompt, response), independent of any subagent mechanism).
- **Mock executor** replays fixtures keyed by `(scenario_id, stage_id, attempt)`,
  materializing each fixture's file contents into the workspace (not just returning
  the summary, since gates read files) — falling back to a small generic synthetic
  set for scenarios with no recorded fixture, used by the orchestrator's own tests.
- **No `--max-turns` flag exists** in the current CLI (P0 finding) — per-call safety
  is `subprocess` `timeout` + `--max-budget-usd`, not a turn-count cap.
- **On timeout, the whole process tree is killed, not just the direct child.**
  `claude -p` can itself spawn further subprocesses (e.g. a Bash tool call); killing
  only the `subprocess.Popen` handle the orchestrator holds would leave those running,
  possibly still writing to the workspace after the orchestrator has already recorded
  the call as `timeout` and moved on. Windows: `taskkill /T /F` against the child's
  PID; POSIX: the child is launched in its own process group and the group is
  signaled. Verified live in T4.1, not just unit-tested (see T4.1 DoD).

### Policies

- **Python classes implementing one `Policy` interface**, parameterized by layered
  config rather than hardcoded values (O-7) — keeps every policy independently
  testable in one shape while leaving the *values* (globs, thresholds) in config,
  which is what a future project-hardening layer would need to mechanically verify
  as tightening-only.
- **Seven of eight policies built this slice**: workspace confinement, path
  partitioning, protected paths (section-aware — `pyproject.toml`'s quality-config
  tables are protected without blocking approved-dependency edits), main protection,
  secret scan (in-house regex, no new dependency), schema change control, and
  diff-size limit. Dependency control is designed but not built (limitation).

### Module layout

Layer-oriented, not stage-oriented (O-9): `engine/`, `stages/` (thin `StageSpec`
bindings, not per-stage packages), `gates/`, `policies/`, `executors/`, `profiles/`,
`workspace/`, `audit/`, `models/`, `cli/`. All nine stages share identical
gate/policy/event-emission plumbing — a stage-oriented layout would fragment that
sharing across nine near-duplicate packages. Full tree in
`docs/architecture-proposal.md` §3.1.

## Consequences

**Positive**
- Zero new runtime dependencies beyond `pydantic`/`pydantic-settings` (already
  present) — `tomllib`, `sqlite3` (unused by choice), threading, and subprocess are
  all stdlib.
- The engine, gates, and policies are testable entirely on the mock executor with no
  network access, satisfying C15-AC1 and the NFR for deterministic tests directly by
  construction, not as an afterthought.
- The executor boundary is thin enough that swapping `claude -p`'s actual invocation
  shape (should the CLI's flags change) touches only `executors/real.py` and
  `profiles/render.py`.

**Negative / accepted risk**
- The custom engine carries more implementation and test burden than adopting a
  library would, in exchange for avoiding a second persistence model.
- Workspace confinement's preventive layer is empirically weaker than originally
  assumed (`--restricted`'s block looked like model judgment, not a hard technical
  guarantee) — the post-stage check is load-bearing, not a backstop for a rare edge
  case.
- `--restricted` removes Bash/code-execution tools globally unless named via
  `--tools` — profile authoring (T4.2) must handle this explicitly for any role that
  needs scoped shell access.
- This slice ships without dependency-control policy, without Change-control/Release
  rejection re-planning, and with duration/call limits as simple fixed checks — see
  `docs/architecture-proposal.md` §4.3's limitations list, carried into
  `docs/engineering-summary.md` (T12.3) verbatim.

## Alternatives considered

| Area | Alternative | Rejected because |
|---|---|---|
| Engine | LangGraph | Duplicate persistence model against the already-mandated file formats; heavy dependency for a fixed, static graph |
| Storage | SQLite | No benefit at this scale; a second source of truth against the mandated flat-file format |
| Config | YAML (PyYAML) | New dependency requiring approval; TOML already matches this repo's own convention with zero new deps |
| Agent contract | Fenced JSON in the response text | Fights the model's native tool-using behavior; a stricter, easier-to-violate contract than a small trailing summary |
| Parallelism | asyncio; a subprocess/process pool | Fixed fan-out of two blocking waits doesn't need async infrastructure or process-pool IPC overhead |
| Workspace confinement | `--add-dir` alone as sufficient confinement | P0 spike: a live write outside it succeeded — no real boundary |
| Profile delivery | Claude Code subagent/skill files | Couples the executor to Claude-Code-specific file conventions; complicates mock-fixture replay and the executor's own filesystem-side-effect boundary |
| Policy expression | Fully declarative rule engine | Several policies (confinement, dependency control) are inherently procedural, not expressible as rules alone |
