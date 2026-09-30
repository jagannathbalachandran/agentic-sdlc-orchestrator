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

## T2.1 — `StageSpec` + minimal static graph (S0, S1) + `StageRunner`

**What changed:** `src/orchestrator/gates/base.py` (`StageContext`, the `Gate`
Protocol); `src/orchestrator/engine/graph.py` (`GRAPH` with S0/S1 only, `T3.2`
extends to all 9); `src/orchestrator/engine/runner.py` (`StageRunner`:
entry gates → execute → exit gates → event → commit hook). Added a generic
`fixtures/mock/_generic/S0.json`. 11 new tests. 99.81% overall coverage
(`executors/mock.py` line 80, a defensive branch for a malformed `files` field,
stays uncovered — not chased, well above the 85% bar).

**Covered:** C4-AC1 (no stage starts before its dependencies pass — `GRAPH`
declares `S1.depends_on == (S0,)`); C4-AC4 (graph lookup rejects unknown stages,
tested via `get_stage_spec` raising `KeyError` for `S2`, not yet defined).

**Deferred / assumed:**
- **Policy enforcement is not stubbed in `StageRunner`.** `Policy.check` needs a
  `WorkspaceDiff` type that doesn't exist until T6.1/T6.2 builds the confinement
  diff mechanism — adding a placeholder `Policy` hook now would mean redesigning
  its signature later anyway, so the "policy (stub)" step from T2.1's own
  description is deferred structurally, not half-built. Noted explicitly since the
  task text mentioned it.
- **The commit step is a no-op hook** (`no_op_commit`, injectable via
  `commit_hook`) until `workspace/git_ops.py` exists (T2.2 for the mechanism,
  T6.1 for the real commit-with-trailers logic).
- **S0 is real-graph orchestrator-only** (no agent call, per requirements.md §7's
  stage table — "S0 Prepare | Orchestrator"). T2.1's test still drives S0 through
  `StageRunner` against the mock executor to prove the generic entry→execute→exit→
  event mechanism stage-agnostically; T2.2/T2.3 will special-case S0 to skip the
  executor call and do real workspace setup instead.
- `StageRunner.__init__`/`run()` take a single `StageGates`/`StageRunRequest`
  argument respectively (not individual params) to stay under the project's
  5-argument limit (PLR0913) — small bundling refactor, same pattern as T1.3's
  `EventDraft`.

## T2.2 — Workspace manager

**What changed:** `src/orchestrator/workspace/{git_ops,manager}.py`;
`src/orchestrator/registry.py` (top-level, matching architecture-proposal.md
§3.1's module tree — it's platform-wide state, not workspace-scoped); added
`GitCommandError` to `exceptions.py`. `registry.resolve_project` is the real
file-backed implementation of the `ProjectLookup` shape `config/validate.py` (T1.2)
was already written against — T2.3 wires it in. 16 new tests. 99.51% overall
coverage (`registry.py` lines 36-37, the corrupt-registry-file fallback, untested
directly but exercised structurally by the missing-file case).

**Covered:** C1 (`register` command backing); C3-AC1/AC2/AC3 (greenfield
init records `base_ref=None` with the setup commit as `base_commit`; existing-repo
clone records the real `base_ref` and its resolved commit — both per G-12's
resolution; run branch created via `create_run_branch`, matching D-5's
`run/<run-id>` naming).

**Deferred / assumed:**
- **Venv creation (C3-AC3's "target deps installed in the workspace venv only")
  is not built.** Not needed until a task actually runs a target's own gates
  (T5.2 template prep / T10 showcase runs) — adding it now with no consumer would
  be exactly the premature-abstraction CLAUDE.md warns against.
- **C3-AC4 (baseline gates run first for non-greenfield) and C3-AC5 (`00-source.md`
  written with its hash recorded) are not built here** — both belong to S0's real
  stage logic, which is orchestrator-side work wired into the graph in T2.3/T3.2,
  not the workspace manager's own job of "does the clone/init mechanically work."
- `git_ops.py`'s `run_git` uses `git` resolved via `PATH` (`# noqa: S607`, matching
  the existing `scripts/check.py` justified-noqa pattern) and a fixed literal
  argument list per call site, never untrusted input (`# noqa: S603`).

## T2.3 — CLI entry + `run`/`register`/`validate`; pause/resume proven

**What changed:** `engine/locking.py` (PID+staleness lock, closes G-2 — platform
branch for `pid_is_alive`: `ctypes`/`OpenProcess` on win32, `os.kill(pid, 0)` on
POSIX, since Windows has no signal-0 liveness check); `engine/fsm.py` (`drive()` —
reload state from disk, run the next pending stage, persist, release the lock);
`cli/main.py` (dispatch), `cli/commands/{register,run}.py`; a
`[project.scripts] orchestrator = ...` entry point added to `pyproject.toml`
(package reinstalled to register it). 24 new tests, including
`tests/integration/test_pause_resume.py` — **the DoD's core proof**: two separate
`python -m orchestrator.cli.main run ... --run-id <same-id>` subprocess
invocations, the first running S0 and exiting, the second reloading `graph.json`
from disk in a fresh process and continuing with S1, with the lock file confirmed
absent between and after both. 96.35% overall coverage — the gaps are expected,
not real: `cli/commands/run.py` lines 51-71 and `cli/main.py`'s `run` dispatch
branch are exercised by the integration test via subprocess, which pytest-cov
can't see into from the parent process; `locking.py`'s POSIX branch of
`pid_is_alive` is exercised by CI (ubuntu-latest) but not locally (Windows dev
box) — both platform branches exist and are exercised somewhere, just not both
in one run.

**Covered:** C1-AC1/AC2 (`register`/`run`/`validate` all work; `run` creates a run
ID and advances it); **directly validates O-1/O-2's pause/resume design** —
architecture-proposal.md's central bet (stateless-process, reload-from-disk) now
has a passing integration test behind it, not just a design doc.

**Deferred / assumed:**
- **`run` advances exactly one pending stage per invocation.** This is an honest
  interim rule, not the final design: production `run` (once T3.1 adds real
  approval checkpoints) should run every pending stage until it hits a checkpoint
  or the graph is exhausted, in one process — matching architecture-proposal.md
  §3.2.1's "between-checkpoint execution... all happens within one process."
  There's no checkpoint logic to loop against yet (T3.1), so "one stage per call"
  is the simplest correct behavior for today's 2-stage graph, and it's exactly
  what let this task prove the reload mechanism directly rather than needing a
  contrived crash-simulation harness.
- **`--run-id` is a testing/internal affordance for now**, not documented as
  normal human CLI usage — it's the same primitive T3.1's `approve`/`reject`/
  `answer` commands will reuse to resume a paused run by its real run ID.
- **Real `run.json` creation (C1-AC2's "record") is deferred to T3.2.** It needs
  registry lookups, an effective-config hash, and real workspace/branch data that
  aren't all wired together yet; writing a placeholder-filled `run.json` now would
  just have to be redone once those pieces exist.
- S0's *real* stage behavior (baseline gates, `00-source.md` with a recorded hash,
  template copy via `workspace.manager`) is still not wired into `fsm.drive()` —
  it runs on the mock executor's generic fixture today. T3.2 connects the real
  workspace manager and gate logic to the graph.

## T3.1 — Approval checkpoints

**What changed:** `models/graph.py` gained `StageSpec.checkpoint_after`
(`ApprovalCheckpointKind | None`) and `GraphState.{scenario_id, pending_checkpoint,
terminal_state}` — `scenario_id` is persisted so `approve`/`reject`/`answer`/`stop`
(invoked with just a run-id) can recover it without the caller re-supplying it.
`audit/approvals_log.py` (append-only `approvals.jsonl`, C7-AC3). `engine/fsm.py`
restructured: `drive()` now pauses when a passed stage's `checkpoint_after` is set
(emits `APPROVAL_REQUESTED`) and no-ops if the run is already paused or terminal;
new `resolve_checkpoint()` (records the decision + comment, clears the pause,
`REJECT_FINAL` → `terminal_state = REJECTED`) and `stop_run()` (→
`terminal_state = STOPPED`) — both take the new `RunRef` (no `scenario_id` needed)
rather than the full `DriveRequest`. `exceptions.py` gained
`NoPendingApprovalError`, `RunAlreadyTerminalError`.
`cli/commands/{approve,reject,answer,stop}.py` (+ a small `_common.py` for the
config/mock-fixtures constants and a one-line status `describe()` shared across
every run-touching command), wired into `cli/main.py` via a dispatch dict (kept
the `if`-chain from growing to 7 branches). 25 new tests. 96.92% overall coverage.

**Covered:** C7-AC1 (pause persists, resumes in a later command — proven the same
way T2.3 proved general reload: a fresh `drive()` call after `resolve_checkpoint()`
continues the graph); C7-AC2 (reject requires a comment — `--comment` is a required
CLI arg on `reject`/`answer`; non-final reject clears the pause without ending the
run, real re-planning is T7.2); C7-AC3 (every resolution recorded: checkpoint,
decision, comment, approver, timestamp — `ApprovalRecord`, already fully specified
by T1.1's model); C1 (`approve`/`reject`/`answer`/`stop` all exist and work).
Lock staleness recovery itself (the rest of "closes G-1/G-2") was already built
and tested in T2.2/T2.3 — not re-tested here, just relied on.

**Deferred / assumed:**
- **No real checkpoint is wired into the production `GRAPH` yet** — S0/S1 still
  have `checkpoint_after=None`. Every checkpoint test (fsm and CLI) monkeypatches
  `orchestrator.engine.fsm.GRAPH` with a small stub graph that does set one, per
  the task's own "stub checkpoint" framing. T3.2 wires real Design/Change-control/
  Release checkpoints into the full S0-S8 graph; at that point the integration
  test could be extended to prove a checkpoint pause through the real `orchestrator
  run` CLI end to end, not just through `drive()`/the command handlers directly.
- **`answer` behaves identically to `approve` mechanically** (decision=`ANSWER`
  instead of `APPROVE`, clears the pause, continues `drive()`). The real product
  difference — a Clarification answer re-running S1 with the answer incorporated,
  rather than just continuing to the next stage — is real S1/graph-wiring logic
  that doesn't exist yet; recording the right decision type today is what T3.1's
  scope asked for.
- **`resolve_checkpoint()` and `drive()` each acquire/release the lock
  separately**, not as one held section — a small window between "resolve" and
  "continue" (both within the same CLI process) where another process could
  theoretically acquire the lock. Not a concern at this build stage; flagged here
  rather than silently accepted.

## T3.2 — Full S0–S8 graph, stub gates, Change-control + Release checkpoints

**What changed:** `src/orchestrator/stages/` — 9 thin modules
(`s0_prepare.py` … `s8_release.py`), each exporting one `SPEC: StageSpec`;
`engine/graph.py` now assembles `GRAPH` from all nine. `S5a→S5b` and `S7a→S7b`
are sequential dependency chains for now (T3.2's own "no parallel yet" scope) —
T6.1's scheduler restores the real parallel-join shape. `gates/{schema_gate,
existence_gate,approval_gate}.py` — `SchemaGate` (stub, always passes) wired as
every stage's entry gate and every non-S2 stage's sole exit gate; `ExistenceGate`
(stub) added as S2's second exit gate; `ApprovalGate` built standalone per the
architecture's module list but **not** wired into any `StageSpec`, since
`fsm.drive()`'s own `pending_checkpoint` check already blocks a paused run
earlier and more directly — documented rather than silently duplicated.
`engine/fsm.py`: `_gates_for()` wires the above into every `StageRunner`
construction; `drive()` and `resolve_checkpoint()` both gained the "all nine
stages passed → `terminal_state = COMPLETED`" check (D-14) — needed in *both*
places, since S8's own completion happens inside `resolve_checkpoint()` (its
Release checkpoint is cleared there, not inside `drive()`'s "stage passed, no
checkpoint" branch). Fixture set completed: `fixtures/mock/_generic/{S2..S8}.json`
alongside the existing S0/S1. 12 new tests (5 gate tests, `engine/graph.py`
rewritten to check the shape of the real 9-stage graph, and the DoD's core proof
— see below). 96.77% overall coverage.

**Covered:** C4-AC3 (`S2 always runs otherwise` half — see deferred note below
for the other half); C5-AC1 partially (every stage has an entry/exit gate; the
"come from the global config" part of C5-AC1 is still deferred, gates are
hardcoded per stage_id, not config-driven — that's O-7/T6.2 territory), C5-AC2
(a failed exit gate raises `StageGateFailure` before any downstream stage
result is recorded — already true since T2.1, exercised now on every stage),
C5-AC3 (every gate result recorded as an event — directly asserted in the new
end-to-end test: 18 `SchemaGate` hits = 2 × 9 stages, 1 `ExistenceGate` hit on
S2); §7 (the full graph shape, both unconditional checkpoints).

**The DoD's core proof:**
`test_end_to_end_real_graph_reaches_completed_through_all_nine_stages` in
`tests/unit/engine/test_fsm.py` drives the real, unpatched `GRAPH` — not a stub —
through all nine stages on the mock executor, resolving the Design checkpoint
(after S3) and the Release checkpoint (after S8) via `resolve_checkpoint()`,
and asserts `terminal_state is RunState.COMPLETED`, every stage `PASSED`, and
every gate actually exercised. Found and fixed a real bug while writing it: the
COMPLETED transition only existed in `drive()`'s per-stage-pass branch, which
S8 never takes (it takes the checkpoint branch instead) — without the fix in
`resolve_checkpoint()`, a run that only ever reached Release approval would
silently never reach `completed`.

**Deferred / assumed:**
- **S2's "skipped for greenfield" half of C4-AC3 is not built.** S2 always runs;
  detecting greenfield-vs-existing (and conditionally skipping) needs
  project-type detection not wired into the graph yet. Documented as a
  limitation at each relevant stage file, not silently omitted.
- **Clarification (after S1) and Change-control (after S6) are not wired.**
  Both are conditional in the real design (blocking questions / risky change)
  and neither detection exists yet (real agent output for the former, T4;
  diff-size/dependency policies for the latter, T6.2) — wiring them
  unconditionally would misrepresent the DECIDED "conditional" semantics more
  than leaving them unwired does. Only Design and Release (both unconditional,
  C7: "always") are wired.
- **Gates are hardcoded per `stage_id` in `fsm._gates_for()`, not config-driven**
  — C5-AC1's "come from the global config" is deferred to whenever a real
  config-driven gate/policy mechanism exists (O-7, T6.2); `StageSpec` doesn't
  carry a gate list of its own yet.
- The integration test's third-process assertion (`tests/integration/
  test_pause_resume.py`) was updated from "nothing to do" (2-stage graph) to
  "ran S2" (9-stage graph) — it still only proves the reload mechanism across
  processes; the full 9-stage-to-completed path is unit-tested (faster, more
  precise), not repeated via subprocess.

## Hard-stop-(b)-review follow-up: `drive()` loops (item 7)

**What changed:** `engine/fsm.py`'s `drive()` no longer advances exactly one
stage per call — it loops (architecture-proposal.md §3.2.1 step 5: "Drive
stages synchronously until the run hits a checkpoint... or fails/stops"),
persisting `graph.json` after *every* single stage (not just once at the end)
so a process killed mid-loop leaves it consistent with `events.jsonl`, not
stale. `DriveResult.ran_stage: StageId | None` became
`ran_stages: tuple[StageId, ...]`. Extracted `_run_one_stage()` (one stage's
full run-record-persist cycle) and a small `_LoopResources` bundle (ref,
executor, event_log, workspace — computed once per `drive()` call, not
per-stage) to keep the loop body and argument counts (PLR0913) manageable.
**New safety property, not previously needed:** a stage that fails now stops
the loop immediately rather than being retried — there's no bounded-retry
logic yet (T7.1), so blindly looping on a failing stage would either spin
forever or (with the real executor) burn real API calls in a tight loop.
`cli/commands/run.py` updated to report every stage the loop ran, or the
paused/terminal status if that's more relevant.
`tests/integration/test_pause_resume.py` rewritten: `run` alone now drives
S0-S3 to the Design pause in one process; a separate `approve` process
resolves it and loops S4-S8 to the Release pause; a third process resolves
that to `completed` — proving reload at a *real* checkpoint boundary, not an
artificial one-stage-at-a-time simulation. 4 new/rewritten unit tests in
`tests/unit/engine/test_fsm.py`, including dedicated proofs that (a) multiple
stages run in one call when nothing pauses them, and (b) a stage failure
stops the loop rather than retrying. 121 tests total, 96.73% overall coverage.

**Sequencing note:** this was implemented and verified as one continuous
change, then split into two commits after the fact (`git stash` on the
CLI/test files while `fsm.py` was reconstructed to its pre-loop state) so the
terminal-state unification (item 2) and the loop (item 7) each landed as their
own reviewable commit, per the reviewer's request — both were verified
independently passing all gates before either commit.

**Deferred / assumed:**
- Still no bounded-retry loop (T7.1) — a failed stage simply stops `drive()`;
  there is no automatic re-attempt, fix-call, or rollback yet. That remains
  exactly T7.1's job; this change only makes the *absence* of retry logic
  safe under looping (stop, don't spin) rather than leaving it unsafe.

## T4.1 — Profile rendering + real executor

**What changed:** `models/profile.py` (`AgentProfile`, TOML-shaped, plus
`DEFAULT_ALLOWED_TOOL_PATTERNS = ("Write", "Edit", "Read")`), `profiles/loader.py`
(`load_profile`: reads + validates a profile TOML, returns `LoadedProfile` with a
sha256 `version_hash` of the raw bytes for traceability), `profiles/render.py`
(`render_system_prompt`, `render_tools_flag`, `render_allowed_tools_flag`), and
`executors/real.py` (`RealExecutor`, the `Executor` implementation backed by real
`claude -p` subprocess calls). Profile is loaded **by name per call**
(`request.profile_name`), not bound at construction, since one `RealExecutor`
instance serves an entire `drive()` loop spanning multiple stages/profiles.
Per-call timeout kills the **whole process tree** (Windows `taskkill /T /F`;
POSIX `os.killpg` + `SIGKILL`, via `CREATE_NEW_PROCESS_GROUP`/`start_new_session`
at `Popen` time), not just the direct child (ADR-001, hard-stop-(a) follow-up).
Workspace venv's `Scripts`/`bin` dir is prepended to the subprocess `PATH` so bare
`python` resolves to the workspace's own interpreter — matching how a shell
`activate` script behaves, and what the developer/test-engineer profiles' scoped
`Bash(python -m pytest *)` pattern (item 4, T4.2) is written against.

**Covered:** O-4 (small JSON execution summary, deliverables via tools), O-6
(`--restricted` + `--add-dir` + `--allowedTools`), O-10 (`--append-system-prompt`
persona injection), ADR-001's process-tree-kill decision.

**Unit tests:** `tests/unit/models/test_profile.py` (3), `tests/unit/profiles/
test_loader.py` (5), `tests/unit/profiles/test_render.py` (6),
`tests/unit/executors/test_real.py` (9, via a patched `subprocess.Popen` stand-in —
timeout→`TIMEOUT`, malformed inner JSON→`INVALID_OUTPUT`, malformed outer
envelope→`INVALID_OUTPUT`, well-formed→`SUCCESS` with every field asserted,
`is_error`→`ERROR`, plus direct tests of `_venv_bin_dir`/`_build_env`/
`_build_command` with and without an enabled-tools profile). Full gate: 144
tests, 96.45% coverage.

**Live tests (DoD requirement, not part of the pytest suite — need a real `claude`
install + network + API budget; run manually from a scratch script, not committed):**
- **Live smoke call:** `RealExecutor.execute()` against a throwaway greenfield
  workspace with a real analyst-shaped profile, prompting it to write
  `01-requirements.md` (one FR + one AC) and reply with the JSON summary contract.
  Result: `outcome=SUCCESS`, `01-requirements.md` landed with the expected content,
  `produced_ids=('FR-1',)`, `files_written=('01-requirements.md',)`, summary parsed
  cleanly, cost ≈ $0.033, ~11s.
- **Live timeout test:** same call shape with `timeout_seconds=1` (deliberately
  impossible). `communicate()` raised `TimeoutExpired` as expected;
  `_kill_process_tree` was called; the direct child's PID was confirmed gone from
  the OS process table (`Get-Process -Id <pid>` empty) immediately after, and no
  file appeared in the workspace even after waiting 15s for a possible late write
  from a surviving grandchild process. Full process-tree termination confirmed.

**Finding (significant, not previously known):** the first smoke-test attempt used
a workspace under the OS temp/scratchpad directory and got `outcome=INVALID_OUTPUT`
with an empty workspace. Raw stdout showed why: `claude -p`'s own permission system
flagged the temp path itself as suspicious and silently blocked the `Write` calls
(`permission_denials` populated; the model's `result` text explained it couldn't
get past "a permission gate flagging the temp/scratchpad path as suspicious") —
this happened *regardless* of `--add-dir`, `--allowedTools Write`, and
`--permission-mode acceptEdits` all being set correctly. Re-running against an
ordinary (non-temp) project directory succeeded immediately. **Consequence:** real
orchestrator workspaces must live under ordinary project directories (which they
already do — `orch_home`/project paths are never OS temp), never under a system
temp directory; documented here so this isn't rediscovered by surprise once T5.2's
real target repos are wired up.

**Deferred / assumed:**
- `--max-turns` doesn't exist (confirmed again, consistent with the P0 spike);
  `--max-budget-usd` + the subprocess timeout remain the only caps.
- No retry/backoff on `TIMEOUT`/`ERROR`/`INVALID_OUTPUT` outcomes yet — that's
  T7.1's job; `RealExecutor` only reports the outcome faithfully.
- pip-audit gate correctly skips auditing this project's own package
  (`orchestrator` isn't on PyPI) — pre-existing gate behavior, not new here.

## T4.2 — Agent profiles (7 roles)

**What changed:** authored `agents/profiles/{analyst,architect,planner,developer,
test_engineer,technical_writer,reviewer}.toml`, one per requirements.md §7's stage
table (C8). Each carries persona, responsibilities (drawn directly from its
stage's row — e.g. analyst covers S1 + S2, architect covers S3, developer is
scoped to exactly one plan task per call for S5a), rules, and the `{summary,
produced_ids, files_written}` JSON output contract (O-4 revised). Profile names
match the `owner_profile` strings already hardcoded in `stages/s*.py` from T3.2
(`analyst`, `architect`, `planner`, `developer`, `test_engineer`,
`technical_writer`, `reviewer`) — no stage-binding changes needed.

**Bash scoping (ADR-001):** only `developer` and `test_engineer` get
`enabled_tools = ["Bash"]` and `Bash(python -m pytest *)` in
`allowed_tool_patterns` (the corrected pattern, per hard-stop-(b) item 4); their
rules explicitly instruct `python -m pytest tests/unit`/`tests/acceptance` —
never a `.venv`-relative path, never bare `pytest` — so what the agent actually
types matches the scoped pattern. Every other profile gets no Bash entry at all.

**Analyst's `blocking_questions` field:** added to the analyst's output contract
(not invented here — requirements.md's S1 exit-gate criteria already says "no
unanswered blocking questions", so the field belongs in S1's real output shape
from the start). Nothing consumes it yet; T7.4 wires the Clarification-checkpoint
pause around it later, exactly as noted in its task entry.

**Covered:** C8 (profiles: persona, responsibilities, allowed tools, output
contract, rules); ADR-001's Bash-scoping decision.

**Tests:** `tests/unit/profiles/test_agent_profiles_toml.py` (new) — asserts the
directory has exactly the 7 expected role files; every profile validates against
`AgentProfile`/`load_profile` (schema, non-empty persona/responsibilities/
output_contract, a real version hash); developer/test_engineer assert the scoped
Bash pattern; every other role asserts no `Bash` anywhere in `enabled_tools` or
`allowed_tool_patterns`. Full gate: 159 tests, 96.45% coverage.

**Deferred / assumed:**
- Profile content (exact prompt wording) is expected to be iterated on during
  T10's real showcase runs, same as O-10 flagged in the P0 spike — this task only
  needed the tool-scoping and schema DoD, not final prompt tuning.

## T5.1 — Greenfield template

**What changed:** `templates/python-service/` — a minimal, generic scaffold that
`workspace/manager.py`'s `init_greenfield_workspace()` (T2.2) copies wholesale
before `git init` + the setup commit. Contains: `pyproject.toml` (packaging +
dev deps + the same ruff/mypy/pytest/coverage config shape as the orchestrator's
own), `scripts/check.py` (the identical 5-gate runner — ruff check, ruff format
--check, mypy --strict, pytest+coverage at 85%, pip-audit), `.github/workflows/
ci.yml` (least-privilege `permissions: contents: read`, pinned actions,
`timeout-minutes`), `src/service/__init__.py` + `tests/unit/test_smoke.py` (a
trivial versioned module + smoke test — needed so a *fresh, uncustomized* copy
already passes its own gates: an empty test suite would exit pytest 5 "no tests
collected", not 0), `tests/acceptance/` (empty, ready for S5b), `.orchestrator/
project.toml` (an example `ProjectConfig`), `README.md`, `.gitignore`.

**Isolation from the orchestrator's own gates:** added `extend-exclude =
["templates/"]` to the root `pyproject.toml`'s `[tool.ruff]` — without it,
`ruff check .` (run from the orchestrator's own `scripts/check.py`) would
recurse into the template and lint it against the *orchestrator's* rules even
though the template ships its own separate `pyproject.toml`/`[tool.ruff]`
(ruff's nearest-config resolution would likely have isolated it anyway, but the
explicit exclude removes any doubt). `mypy --strict` was already scoped to
`src tests scripts` so it never touched `templates/` in the first place;
`pytest`'s `testpaths = ["tests"]` never collects `templates/python-service/
tests/` either.

**Covered:** §12 setup, C3-AC2.

**Tests:** `tests/unit/templates/test_python_service_template.py` (new, 5
tests) — asserts every expected scaffold file exists; `.orchestrator/
project.toml` validates against `orchestrator.config.schema.ProjectConfig`
(reusing `config/loader.py`'s `load_project_config`, T1.2); the CI workflow
pins actions and sets `permissions`/`timeout-minutes`; `scripts/check.py`
declares the same 5 gates as the orchestrator's own. Full gate: 164 tests,
96.45% coverage.

**Live verification (DoD's "copying the template and running its own
CI-equivalent quality gates locally succeeds on a fresh copy" — a real `pip
install` into a throwaway venv, not part of the pytest suite, same category as
T4.1's live tests):** copied `templates/python-service/` to a scratch sibling
directory, created a fresh venv, ran `pip install -e ".[dev]"` (succeeded,
`service 0.1.0` installed editable), then `python scripts/check.py` — all 5
gates passed cleanly: 1 test passed, 100% coverage (85% required), no
vulnerabilities found. Confirms a target repo built from this template is
gate-green *before* any orchestrator run even starts.

**Deferred / assumed:**
- The scaffold's `src/service/` module and its smoke test are meant to be
  extended/replaced by S5a's real implementation tasks, not treated as
  permanent application code.
- `.orchestrator/project.toml` here is the template's own illustrative example
  (`project_name = "python-service"`); T5.2 writes the *real* target repos'
  `.orchestrator/project.toml` once those repos exist (human-owned task, not
  this one).

## T5.2 — Target repo prep

**Ownership:** repo creation, the `url-shortener-brownfield-target` copy of A1,
and pushing the `baseline-greenfield` tag were all done by the user (human-owned
per the task split). Claude's part: author `.orchestrator/project.toml` in each,
register both, and check the Postgres question — no repo creation/copying/
pushing.

**What changed:**
- `shortener-greenfield-by-agents` (empty, local
  `C:\Users\Prathibha\projects\shortener-greenfield-by-agents`, remote
  `github.com/jagannathbalachandran/shortener-greenfield-by-agents`): added
  `.orchestrator/project.toml` — `project_name = "shortener-greenfield-by-agents"`,
  `approved_dependencies = []` (greenfield builds fresh from the T5.1 template,
  not this repo's history; the stack is decided during Design/Plan, any new
  dependency goes through Change-control, C6/T6.2).
- `url-shortener-brownfield-target` (copy of A1 with A1's remote removed, tag
  `baseline-greenfield` at `976f316` "T-04: redirect, link details, 404 for
  unknown codes", local
  `C:\Users\Prathibha\projects\url-shortener-brownfield-target`, remote
  `github.com/jagannathbalachandran/url-shortener-brownfield-target`): added
  `.orchestrator/project.toml` — `project_name =
  "url-shortener-brownfield-target"`, `approved_dependencies` listing the 7
  production deps already in `pyproject.toml` at that tag (`fastapi`,
  `pydantic`, `pydantic-settings`, `uvicorn`, `sqlalchemy`, `alembic`,
  `psycopg`) — pre-approved since they predate any orchestrator run; a new one
  the agents add later still needs Change-control approval.
- Both registered via the real `orchestrator register` CLI against the default
  `ORCH_HOME` (`~/.orchestrator` — confirmed **not** an OS temp path, consistent
  with T4.1's finding; `cli/main.py:default_orch_home()` resolves to
  `Path.home() / ".orchestrator"` unless `$ORCH_HOME` overrides it). Verified
  both resolve via `registry.resolve_project`.

**Postgres finding (checked against `url-shortener-brownfield-target`, not
A1):** checked out the `baseline-greenfield` tag, unset `DATABASE_URL`, and ran
its `scripts/check.py` with its own `.venv` — **all gates passed without a
running Postgres instance**: 80 tests passed, 97.67% coverage (85% required),
ruff/mypy/pip-audit clean. Confirmed by reading `tests/conftest.py`:
`_database_url()` falls back to a throwaway `tmp_path` SQLite file (migrated to
head via Alembic) whenever `DATABASE_URL` is unset; `docker-compose.yml`'s
Postgres service is explicitly for "optional manual runs" only (its own
comment), never required by the test suite. **Mitigation:** none needed — the
orchestrator's real executor never sets `DATABASE_URL`, so agent-run test
gates against this project will use the same SQLite fallback by default.
Repo was returned to `main` (its state before this check) after the tag
checkout.

**Covered:** §12, C3-AC4.

**Deferred / assumed:**
- No orchestrator source changed in this task; only files written into the two
  external target repos plus the registry entry at `~/.orchestrator/
  projects.json` (outside this repo, not committed here).
- T5.3 (scenario REQ text) is next and depends on this task.

## T5.3 — Scenario REQ text (B-1 + G-16)

**What changed:** three `.orchestrator/scenarios/*.toml` files, one per
requirements.md §12 row, written into the two target repos from T5.2 (files
live outside this repo, not committed here):
- `shortener-greenfield-by-agents/.orchestrator/scenarios/greenfield.toml` —
  `req_id = "REQ-1"`, no `base_ref` (workspace built fresh from the T5.1
  template, never cloned). `requirement_text` broadens §12's bare "Shorten,
  redirect, 404 for unknown codes" per architecture-proposal.md B-1, explicitly
  adding all three reliability behaviors B-1 names: reject malformed input
  with a clear 4xx (not a crash/500); unknown code → 404 (not an exception);
  generated codes must never collide.
- `url-shortener-brownfield-target/.orchestrator/scenarios/brownfield.toml` —
  `req_id = "REQ-1"`, `base_ref = "baseline-greenfield"`, `inject_fault =
  true` (G-16's flag — the orchestrator itself writes one failing acceptance
  test immediately before S6's first attempt, forcing the S6→S5a retry loop
  on demand rather than depending on a real agent happening to fail).
  `requirement_text` = "Add click analytics" per §12, fleshed out from
  `url-shortener-brownfield-target`'s own `docs/requirements.md` (a
  pre-existing human-authored doc found already in the copied repo) —
  FR-1..FR-4 already exist there for the greenfield features; FR-5/FR-6 are
  explicitly earmarked "Brownfield" for exactly "record each redirect as a
  click" / "stats per link: total clicks, clicks per day, top referrers", so
  this REQ text continues that numbering rather than inventing new scope. Also
  carried over that doc's non-functional constraint that recording a click
  must never slow the redirect hot path, and its privacy constraint (no raw
  IPs stored).
- `url-shortener-brownfield-target/.orchestrator/scenarios/ambiguous.toml` —
  `req_id = "REQ-2"`, `base_ref = "baseline-greenfield"` (independent of the
  brownfield scenario — same base tag, not chained after it), `inject_fault`
  left at its default `false` (G-16 is brownfield-only; this scenario
  demonstrates blocking questions and design rejection instead, not the
  S6→S5a retry). `requirement_text` = exactly `"Links should expire."` per
  §12 — deliberately **not** fleshed out: that same `docs/requirements.md`'s
  Q-6 explicitly says expiry behaviour (who sets it, the expired-link
  response, the default) is "resolved in the ambiguous scenario" — i.e. by
  S1 raising `blocking_questions` into the Clarification checkpoint (T7.4),
  not by this REQ text pre-deciding it. Over-specifying it would defeat the
  scenario's purpose.

**Covered:** B-1, G-16, §12.

**Verification (DoD):** ran the real `orchestrator validate` CLI (not a mock
or a test stub) against all three, using T5.2's actual registered project
names and the orchestrator's own `config/defaults.toml` — all three printed
`OK`. Explicitly checked the greenfield REQ text against B-1's three named
reliability behaviors by grepping for each: malformed-input rejection ✓,
404-not-crash ✓, collision-avoidance ✓ — all three present verbatim.

**Deferred / assumed:**
- No orchestrator source changed; scenario files live in the two external
  target repos (the user commits/pushes them there, per T5.2's ownership
  pattern).
- `url-shortener-brownfield-target`'s own `docs/requirements.md` (copied over
  from A1) was read for grounding only — not modified, and not something this
  orchestrator repo depends on or references at runtime.

## T6.1 — Parallel join (S5, S7)

**What changed:**
- `stages/s5b_acceptance_tests.py`: `depends_on` changed from
  `(S5A_IMPLEMENT,)` to `(S4_PLAN,)` — S5a/S5b are now true siblings, both
  depending only on S4, instead of chained.
- `stages/s7b_review.py`: `depends_on` changed from `(S7A_DOCS,)` to
  `(S6_VERIFY,)` — same shape for S7a/S7b.
- `stages/s6_verify.py` and `stages/s8_release.py`: **also** updated (not
  explicitly called out in the task text, but a correctness requirement of
  making S5a/S5b and S7a/S7b real siblings) — `depends_on` changed from just
  the "b" member to **both** members of the pair
  (`(S5A_IMPLEMENT, S5B_ACCEPTANCE_TESTS)`, `(S7A_DOCS, S7B_REVIEW)`). Without
  this, the join stage could start as soon as its *faster* sibling passed,
  while the other was still running — the old single-dependency chain only
  worked because the chain itself guaranteed both had passed by construction.
- `engine/scheduler.py` (new): `run_batch()` — runs 1 spec directly, or 2+
  concurrently via `ThreadPoolExecutor` (one thread per spec), joined before
  returning. No locking here; concurrency safety lives in the callees.
- `engine/fsm.py`: `_next_pending_stage` (single spec) replaced with
  `_next_ready_batch` (tuple of every currently-ready spec — 1 normally, 2 for
  a sibling pair; nothing hardcodes which stages pair up, it falls out of the
  graph's `depends_on` shape alone). `_run_one_stage` split into
  `_build_runner`/`_build_request` (construct a `StageRunner`/`StageRunRequest`
  per spec) and `_record_batch_result` (post-run bookkeeping — StageResult,
  checkpoint, completion — run only on the main thread, after the whole batch
  joins, so no lock is needed there). `drive()`'s loop now runs a batch per
  iteration and persists `graph.json` once per batch (not per stage within it).
- `engine/runner.py`: added `stage_commit_hook` — **the first real commit
  hook** (previously `no_op_commit` was the only one wired in; nothing called
  `git_ops.commit_all` from `drive()` at all before this task). One commit per
  stage call unless `commit_strategy` is `NONE`; message is
  `"<stage>: stage complete"` (T8.1 owns real trailer formatting later).
- `workspace/git_ops.py`: `commit_all` now serializes via a module-level
  `threading.Lock` (`_COMMIT_LOCK`) so two branches' `git add -A && git commit`
  never race the same working tree/index. Because `git add -A` is
  workspace-wide (no per-stage path scoping without T6.2's path-partitioning
  policy), a sibling branch's commit — run first — can already cover this
  branch's files by the time this call acquires the lock; `commit_all` detects
  that (`git diff --cached --quiet` after staging) and returns the current
  HEAD instead of attempting an empty commit, which `git commit` would
  otherwise reject. `audit/event_log.py` already had its own internal lock
  (built ahead of this task, per its existing docstring) — nothing to change
  there.
- `engine/fsm.py`'s `drive()` now also calls `workspace/git_ops.init_repo()`
  on the workspace unconditionally (idempotent — a no-op if it's already a git
  repo) instead of just `workspace.mkdir()`. **Necessary, not just tidy:**
  once `stage_commit_hook` makes real commits, every stage from S1 onward
  needs the workspace to already be a git repo — and nothing currently does
  that (S0's real prepare logic — registry lookup, template copy or clone —
  isn't wired into `drive()`/`run.py` yet; that integration remains a real,
  separate gap, not this task's to close). This is the minimum viable fix so
  `drive()` doesn't crash on its very first commit, both for tests and for
  real `--mock`/`--real` CLI usage.

**Covered:** C4-AC2, §7.3; closes G-3.

**Tests:**
- `tests/unit/engine/test_graph.py`: topology assertions rewritten for the
  sibling shape (`test_s5a_and_s5b_are_parallel_siblings_both_depending_only_on_s4`,
  `test_s6_joins_both_s5a_and_s5b`, and the S7/S8 equivalents).
- `tests/integration/test_parallel_scheduler.py` (new — the DoD's required
  test): drives a real 9-stage run against a real (`tmp_path`) git repo with a
  `MockExecutor` wrapped to inject a small artificial delay on S5a/S5b calls
  only, recording each call's actual wall-clock interval. Asserts the two
  intervals **overlap** (direct proof of concurrency — more robust than
  inferring it from total elapsed time, which real git subprocess overhead
  from S4/S7a's own commits in the same `drive()` call would swamp), both
  file sets land (`src/placeholder.py` + `tests/unit/test_placeholder.py` from
  S5a, `tests/acceptance/test_fr1.py` from S5b), both stages recorded a
  commit, `git fsck` raises nothing, and `git status --porcelain` is empty
  (fully committed, no corruption or leftover dirt).
- 5 previously-passing `tests/unit/engine/test_fsm.py` tests that call
  `drive()` against the real graph needed no changes in the end — they were
  broken by the real-commit-hook change (git commands failing against a
  non-git tmp_path) but are fixed by `drive()`'s own `init_repo()` call above,
  not by any test-side workaround (a test-local git-init helper was written,
  then reverted once the real fix — `init_repo()` inside `drive()` itself —
  made it redundant).
- Full gate: 169 tests, 96.63% coverage.

**Deferred / assumed:**
- `stage_commit_hook`'s commit messages are minimal (`"<stage>: stage
  complete"`) — T8.1 owns real trailer formatting (`Task:`/`S5a-fix`/etc.).
- `CommitStrategy.ONE_PER_TASK` (S5a) is still treated the same as `ONE` (one
  commit for the whole stage call) — a real per-task loop inside S5a isn't
  built yet; `rendered_prompt` is still the generic `f"stage {stage_id}"` from
  T3.2's walking-skeleton scope, unchanged by this task.
- S0's real workspace preparation (registry lookup → clone or template copy)
  remains unwired into `drive()`/`run.py` — `init_repo()` is the minimum this
  task needed (a real commit target), not a substitute for that real logic.
- `git add -A`'s workspace-wide scope means two concurrent branches can
  collapse into a single shared commit if their timing overlaps enough
  (documented in `commit_all`'s docstring) — both branches' changes still land
  correctly either way; T6.2's path-partitioning policy is the natural place
  to scope each branch's `git add` to only its own allowed paths, if that
  distinction ever matters later.

## T6.2 — Policies (7 of 8) + Change-control checkpoint

**What changed:**
- `policies/base.py` (new): `WorkspaceDiff`/`FileChange` (the shared input
  every policy checks against), `PolicyOutcome` (`ok`/`change_control`/
  `critical`), `PolicyResult`, the `Policy` protocol, and `compute_diff()` —
  builds a `WorkspaceDiff` from real `git diff`/`git branch` output between a
  base commit and HEAD. Policies are evaluated **once at S6**, against the
  whole run's accumulated diff, not per-stage — S6 has no way to attribute a
  changed file back to the stage that wrote it (two sibling stages can even
  share one commit, T6.1's `git add -A` collapse).
- 7 policy modules (`workspace_confinement.py`, `path_partitioning.py`,
  `protected_paths.py`, `main_protection.py`, `secret_scan.py`,
  `schema_change_control.py`, `diff_size_limit.py`) — dependency control
  descoped per the task's own scope note (not built this slice). Each is a
  small, independently-configured class with one `check(diff) -> PolicyResult`
  method.
- `policies/registry.py` (new): `build_default_policies()` — the CLI's one
  integration point with real config (`config/defaults.toml`, cwd-relative,
  matching `cli/commands/_common.py`'s existing convention) and the stage
  graph's own `allowed_write_paths`. Kept out of `engine/fsm.py` itself so
  `drive()` stays config-path-agnostic — `policies` defaults to `()` there,
  not a lazily-loaded real set, so every existing test that doesn't care about
  S6 policies needed no changes.
- `engine/fsm.py`: `drive()` gained a `policies: tuple[Policy, ...] = ()`
  param, threaded through to a new `_evaluate_s6_policies()` (called from
  `_record_batch_result` specifically when S6 passes — the dynamic-checkpoint
  primitive the task asked for: S6's own `StageSpec.checkpoint_after` stays
  `None`, same mechanism T7.4 will reuse for Clarification). Worst outcome
  wins: any `critical` hit sets `terminal_state = STOPPED` (+ a `stop` event,
  C9's "critical violation"); otherwise any `change_control` hit sets
  `pending_checkpoint = CHANGE_CONTROL` (+ `approval_requested`); otherwise S6
  falls through to the normal completion check, same as any other stage.
  Every policy's verdict is recorded as its own `policy_result` event
  (C6-AC2: policy ID, outcome, evidence).
- `models/graph.py`: `GraphState` gained `base_commit: str | None` — captured
  once, at a run's very first `drive()` call (right after `init_repo`), so S6
  always diffs *this run's* changes, not the target repo's whole history. A
  brand-new, zero-commit workspace uses git's well-known empty-tree SHA
  (`git_ops.EMPTY_TREE_SHA`) as the sentinel base.
- `cli/commands/{run,approve,reject,answer}.py`: each now passes
  `policies=build_default_policies()` to its `drive()` call — the only 4 real
  integration points; every other caller (tests) keeps the empty default.
- `config/schema.py`/`config/defaults.toml`: `PolicyConfig` gained
  `migration_path_globs` (default `()`, so old configs still validate), with
  real defaults covering both root-level and nested `migrations/`/
  `alembic/versions/` layouts (fnmatch's `*` doesn't stop at `/`, so
  "migrations/\*" and "\*/migrations/\*" both needed listing explicitly).
- Every agent-driven stage's `StageSpec` (`stages/s*.py`) gained
  `allowed_write_paths`, matching the T4.2 profiles' own stated
  responsibilities exactly (e.g. developer -> `src/**`+`tests/unit/**`, test
  engineer -> `tests/acceptance/**`) — `path_partitioning`'s config is the
  *union* of these across the whole graph (`registry.py`), since it can't
  attribute a file back to one stage either.

**Two real, pre-existing bugs this surfaced and fixed (not T6.2's own new
code, but blocking it from working at all):**
1. **No `run/<run-id>` branch was ever created.** D-5 requires the run branch
   before any stage executes, but nothing wired `workspace/manager.py`'s
   already-built `create_branch()` into `drive()` — every run silently stayed
   on `main`. `main_protection`'s very first real exercise (via the CLI) caught
   this immediately (correctly stopping the run) rather than masking it.
   Fixed by adding `git_ops.ensure_on_branch()` (idempotent: creates the
   branch if new, switches if it exists, no-ops if already on it) and calling
   it from `drive()` right after `init_repo()` — same "necessary, not just
   tidy" pattern as T6.1's `init_repo()` call.
2. **`git rev-parse --abbrev-ref HEAD` fails on a zero-commit repo** ("fatal:
   ambiguous argument 'HEAD'") — used both by the new `ensure_on_branch`/
   `current_branch` and by `compute_diff`'s branch lookup. Fixed by switching
   to `git symbolic-ref --short HEAD`, which resolves the *pending* branch
   name regardless of whether it has any commits yet.

**Covered:** C6-AC1/AC2 (7 of 8 policies); C7 (Change-control checkpoint).

**Outcome-severity judgment calls (C6's bullet list names outcomes for
main-protection, secret-scan, schema-change-control, and diff-size-limit
explicitly; workspace-confinement and path-partitioning aren't given one) —
documented, not silently assumed:**
- `workspace_confinement` and `path_partitioning` are both treated as
  **critical** — the same severity class as main-protection/secret-scan, on
  the reasoning that an agent writing outside its confinement/scope boundary
  is a containment breach, not a "needs a human to weigh in" situation.
- `protected_paths` is also treated as **critical** (not explicitly stated
  either) — tampering with CI/quality-gate config or a secrets-file path is
  reasoned the same way.

**Tests:** `tests/unit/policies/` (new directory) — one file per policy, each
proving detection *and* the specified/assumed outcome (C6-AC1's literal
requirement) plus a clean-diff pass case; `protected_paths` additionally
proves G-4's section-aware distinction with a real 2-commit git repo (editing
`[tool.ruff]` is flagged, editing `[project.dependencies]` alone is not).
`test_base.py` (compute_diff against a real repo), `test_registry.py`
(`build_default_policies` + the allowed-path-globs union covers every real
generic-fixture output). `tests/unit/workspace/test_git_ops.py` extended for
`ensure_on_branch`/`current_branch`/`current_commit_or_empty_tree`/
`read_file_at_commit`. `tests/unit/engine/test_fsm.py` gained the DoD's
required test (a `schema_change_control` violation sets `pending_checkpoint =
CHANGE_CONTROL`; a clean diff does not — same stub-graph pair) plus a third
proving the `critical` path ends the run `stopped`, not just paused. Full
gate: 210 tests, 97.14% coverage.

**Deferred / assumed:**
- Dependency control (8th policy) stays out of scope this slice, exactly as
  the task named — `[project.dependencies]` edits pass unblocked through
  `protected_paths`' section-aware check by design (G-4), but nothing yet
  checks a new dependency against a project's approved list.
- S0's real workspace preparation (registry lookup, clone/template copy) is
  still unwired — `drive()` now does exactly two minimum-viable pieces of that
  job (`init_repo`, `ensure_on_branch`), not a substitute for the real thing.
- `stage_commit_hook`'s commit messages remain minimal; T8.1 still owns real
  trailer formatting.

## T7.1 — Bounded retries, rollback, safe-stop

**What changed:**
- `engine/fsm.py`: a failing stage no longer breaks `drive()`'s loop outright.
  `_record_batch_result` now computes each stage's real attempt count (it was
  hardcoded to `1` before this task) and routes a non-PASSED result to
  `_handle_stage_failure`: if attempts remain, the stage is simply left
  `FAILED` and `_next_ready_batch` naturally re-selects it next iteration (no
  bespoke "retry this one stage" path needed — reusing the existing
  batch-selection machinery); if exhausted, `_fallback_to_human` sets
  `terminal_state = FAILED` (C9: "pause for the human... end as failed", not a
  silent stop) with a `stop` event carrying the attempt count and reason.
  `ReliabilityLimits` (new, bundling `RetryLimits` + `max_agent_calls`) is a
  new `drive()` param defaulting to safe built-in numbers matching
  `config/defaults.toml`'s own (2/3/2, 60) — same "stay cwd-independent"
  reasoning as T6.2's `policies` param; nothing wires a real-config-loaded
  version into the CLI yet since none of the 4 commands needed to override the
  defaults this task.
- Three separate bounded-retry counts, per C9/G-13/G-15: `S6` gets
  `s6_failure_max_attempts` (3) and, before each retry, **one fix call**
  (`_run_fix_call` — a synthetic S5a-shaped developer call, `commit_hook=
  no_op_commit` + an explicit `commit_all` afterward so it's never attributed
  to `stage_commit_hook`'s normal per-stage commit) rather than a full S5a
  re-run (G-13); `S7b` gets `s7b_findings_max_attempts` (2), triggered not by
  `StageStatus.FAILED` but by `AgentCallResponse.high_severity_findings` being
  non-empty *even when the call itself PASSED* (S7b can succeed as a call
  while still reporting a problem) — its fix call additionally invalidates
  **S6, S7a and S7b** (`_invalidate`, `StageStatus.INVALIDATED`), not just
  S7b, since a findings-driven fix can change what S7a already documented
  (G-15, mirroring C11-AC2). Everything else gets `invalid_output_max_attempts`
  (2) with no fix call — a plain same-stage retry. `_max_attempts_for` picks
  the count; there's no real per-outcome signal today distinguishing "invalid
  output" from any other generic failure, so that count is used for every
  non-S6/S7b stage uniformly (documented limitation, not silently assumed).
- `AgentCallResponse` gained `high_severity_findings: tuple[str, ...] = ()`
  (mirrored into `MockExecutor`/`RealExecutor`'s response construction, and
  the reviewer profile's own output contract) — S7b's real trigger signal,
  not inferred from parsing `04-review-findings.md`.
- `GraphState` gained `started_at`, `last_checkpoint_commit`, and
  `agent_call_count`. `last_checkpoint_commit` is updated in
  `_record_batch_result` for **every** `PASSED` stage regardless of whether it
  committed (G-14: "record an explicit checkpoint... whether or not that
  stage itself committed" — several stages commit 0 times). `started_at` is
  captured once, at a run's first `drive()` call, for the new safe-stop
  duration check; `agent_call_count` increments once per real executor call
  (including fix calls) for the new safe-stop call-count check.
- `_check_safe_stop_limits` (C9): runs once per batch, after
  `_record_batch_result`; stops the run (`terminal_state = STOPPED` + a `stop`
  event naming the trigger) if `agent_call_count` or elapsed wall-clock time
  exceeds `reliability`'s limits. Guarded against overwriting a
  `terminal_state` a stage's own completion/checkpoint logic *just* set in the
  same batch (a real bug caught while writing its own test: a 2-stage stub
  graph's last stage both completing the run *and* tripping the call-count
  cap in the same batch would otherwise have silently replaced `COMPLETED`
  with `STOPPED`).
- `engine/scheduler.py`: `run_batch` now catches `StageGateFailure` (a gate
  rejection) and converts it to a `FAILED` `StageRunResult` instead of letting
  it propagate as an uncaught exception — this was a real, previously-latent
  gap (never exercised, since every gate is still a stub that always passes)
  that would have silently crashed `drive()` the first time any gate ever
  failed; T7.1's retry logic needs every failure mode to reach it uniformly.
  `StageRunner.run()` itself still raises `StageGateFailure` (its documented,
  directly-tested contract) — only this one calling layer catches it.
- `workspace/git_ops.py`: `rollback_to` now also runs `git clean -fd` after
  `git reset --hard` — `reset --hard` alone leaves untracked files behind
  (correct git behavior, but not what "reset to the checkpoint" should mean
  here — an agent's stray uncommitted file isn't "at the checkpoint" either).
  `git clean` still respects `.gitignore` (no `-x`), so the workspace venv and
  other ignored build artifacts are never touched.
- `engine/fsm.py`: new `rollback_to_checkpoint(ref, max_run_duration_seconds)`
  — a manual recovery action (not auto-invoked by the retry loop, since it
  discards work and that's a human's call to make), resetting the workspace to
  `graph_state.last_checkpoint_commit`. Raises the new
  `NoCheckpointRecordedError` if nothing has ever passed yet.
- Two more real, previously-latent bugs this task's own tests caught (not new
  code from this task, but blocking it): `policies/base.py`'s `compute_diff`
  used a literal `git rev-parse HEAD`/`git diff ... HEAD`, which fails on a
  workspace with zero commits (S6 can legitimately run with none, if every
  upstream stage in a given graph has `commit_strategy=NONE`) — fixed by
  routing through `current_commit_or_empty_tree` like T6.1/T6.2's other
  zero-commit-safe call sites. Separately, `_build_request` never actually
  read the stage's current attempt count from `graph_state` — every call used
  the `StageRunRequest.attempt` default of `1`, meaning a retried stage's mock
  fixture lookup could never key off a real second attempt; without this fix,
  none of this task's own retry-success tests could pass a stage on its
  second try.

**Covered:** C9-AC1, C9-AC2, C9-AC3, C9-AC5; G-13; G-14; G-15.

**Tests:** `tests/unit/engine/test_fsm.py` — one test per bounded loop hitting
its max (generic/S0, S6, and the safe-stop cap) and one proving a successful
retry for each of S6 (fix call → passes) and S7b (fix call → S6/S7a/S7b
invalidated and re-run → clean second pass completes the run), all asserting
`attempts`, `ran_stages` repetition, and the `stop`/`policy_result` event
payloads carry full context (reason, attempt count). A rollback test
(uncommitted stray file discarded, workspace lands exactly on the recorded
checkpoint commit) and a `NoCheckpointRecordedError` test. The pre-existing
"stage failure stops the loop" test (T3.2-era, explicitly about the *absence*
of retry logic) was rewritten to prove the *bounded* retry-then-fallback
behavior instead, since its original premise no longer holds. Full gate: 216
tests, 96.94% coverage.

**Deferred / assumed:**
- Full structured commit trailers for fix-call commits (`Stage: S5a-fix` +
  `Task`/`FR`, as G-13 specifies) are still just a distinguishable commit
  *message* — T8.1 owns real trailer formatting, same deferral as T6.1's
  `stage_commit_hook`.
- `ReliabilityLimits` isn't yet wired into any CLI command with a
  config-loaded (non-default) value — none of the 4 commands needed one this
  task; the same `policies.registry`-style factory would be the natural place
  if that's ever needed.
- `rollback_to_checkpoint` is deliberately not auto-invoked anywhere (not
  after a fallback-to-human, not on `stop`) — G-14 describes the mechanism,
  not when to use it automatically, and discarding work automatically felt
  like the wrong default to assume without a clearer spec signal.

## T7.2 — Design-rejection re-planning

**What changed:** `engine/replanning.py` (new) — `invalidate_from(graph_state,
stage_id)`: marks `stage_id` and everything transitively downstream of it (via
`GRAPH`'s own `depends_on` edges) `StageStatus.INVALIDATED`, returning the
affected stage IDs in graph order for the caller to record on the triggering
event (C11-AC2). That's the entire mechanism — no bespoke "re-run these
stages" path was needed: `engine/fsm.py`'s existing batch-selection machinery
(`_next_ready_batch`) already re-selects any stage that isn't `PASSED`, and
`INVALIDATED` already existed as a `StageStatus` value (built ahead of this
task, evidently anticipating it).

`engine/fsm.py`'s `resolve_checkpoint` gained a new branch: `ApprovalDecision.
REJECT` (not `REJECT_FINAL`) on a `DESIGN` checkpoint calls `invalidate_from(
graph_state, StageId.S3_DESIGN)` and records an `EventType.RETRY` event
(`{"trigger": "design_rejection", "invalidated": [...]}`) instead of falling
through to the plain "clear the checkpoint" path every other decision takes.
S1/S2 (upstream of S3) are untouched, matching C11-AC1 literally.

**Re-approval, not a shortcut around it (C11-AC3):** S3's `StageSpec.
checkpoint_after` is still `DESIGN` regardless of whether this is an original
run or a re-plan, so re-running S3 pauses at Design again — a re-plan goes
through the *same* approval a first attempt would, not around it. Only after
that second Design approval does `drive()` actually proceed into S4 onward.

**Covered:** C11-AC1, C11-AC2, C11-AC3.

**Tests:** `tests/unit/engine/test_fsm.py`'s
`test_reject_design_with_feedback_reruns_s3_onward_keeping_s1_s2` drives the
**real** 9-stage graph (not a stub — `replanning.py` imports the real `GRAPH`
directly, matching how it's actually used in production) through the full
sequence: reject Design with feedback -> asserts S3..S8 are `INVALIDATED` and
S0/S1/S2 stay `PASSED` -> asserts the `retry` event's payload -> a further
`drive()` call re-runs *only* S3 and pauses at Design again -> approving that
re-runs S4 through S8 for real (asserted via `ran_stages`), pausing at
Release. Full gate: 217 tests, 96.98% coverage.

**Deferred / assumed:**
- Change-control/Release rejection re-planning (G-9's broader extension of
  this same idea) stays designed-only, exactly as the task named — this task
  only wires Design's rejection path.
- Mock fixtures don't model "the analyst/architect actually used the
  feedback" — S3's re-run replays the same generic fixture (same content) —
  proving the *mechanism* (re-run happens, gates re-evaluate, approval is
  required again) rather than that feedback changes the output, which isn't
  something the current fixture format can represent.

## T7.3 — Fault-injection hook (G-16)

**What changed:** `GraphState` gained `inject_fault` (whether this run's
scenario flagged injection) and `fault_injected` (whether it has already
happened this run — a guard against a later, unrelated invalidation cascade,
e.g. T7.1's S7b-findings retry resetting S6's attempt counter to 0, being
mistaken for a fresh "attempt 1" and re-triggering injection a second time).
`DriveRequest` gained `inject_fault`, copied onto a brand-new `GraphState` the
first time one is created for a run (same pattern as `base_commit`) — it's
meaningless on a resumed run's `DriveRequest` (approve/reject/answer rebuild
one from just `scenario_id`), since the flag already persisted into
`GraphState` on the run's first `drive()` call.

`engine/fsm.py`'s `_record_batch_result` checks, right after computing a
batch member's attempt count: if this is S6, `inject_fault` is set, it hasn't
fired yet, and this is attempt 1 — `_inject_fault()` writes
`tests/acceptance/test_injected_fault.py` (a deterministically failing test,
content included directly since there's no real "run the target's test
suite" mechanism yet to make an actually-failing test file matter — Phase 1
scope, same boundary T6.2's S6 already documented) and appends an
`EventType.FAULT_INJECTED` event with `injected=True` (a first-class
`EventDraft` field built well before this task, evidently anticipating it).
The batch member's `StageRunResult` is then replaced (frozen dataclass, so a
new instance) with `status=FAILED`, `commit=None` — forcing exactly the one
S6 failure G-16 asks for, regardless of what the executor's own S6 fixture/
call would otherwise have produced. From there, **T7.1's existing S6-failure
retry logic runs completely unmodified** — one developer fix call, then S6's
attempt 2 (no re-injection, since `fault_injected` is now `True`) proceeds
normally.

**Covered:** G-16.

**Tests:** `tests/unit/engine/test_fsm.py`'s
`test_fault_injection_forces_one_s6_failure_then_a_normal_retry_passes` —
S6's own fixture would `PASS` on every attempt if not for the forced
override (proving the *injection*, not a missing fixture, causes the first
failure); asserts the injected file lands in the workspace, `attempts == 2`,
`fault_injected` flips `True`, and the `fault_injected` event's payload names
the file and carries `injected: true`. Full gate: 218 tests, 97.01%
coverage.

**Deferred / assumed:**
- `run.py` (and the other 3 CLI commands) don't yet load a scenario's real
  `inject_fault` flag from its `.orchestrator/scenarios/<id>.toml` — that
  needs project-registry -> target-repo-path -> scenario-config resolution
  that doesn't exist anywhere in this codebase yet (a larger, pre-existing gap
  already flagged in T6.1/T6.2's build notes, not created by this task).
  `DriveRequest.inject_fault` defaults to `False` for all real CLI usage today;
  the mechanism is fully built and tested, just not yet wired to a real
  config-loaded value — T5.3's brownfield scenario TOML already carries
  `inject_fault = true`, ready for whenever that wiring lands.
- The injected test's content doesn't get run against any real test suite
  (none exists yet) — its presence in the workspace, and the forced `FAILED`
  status, are what stand in for "the test actually failed" in Phase 1's engine.

## T7.4 — Clarification checkpoint

**What changed:** `AgentCallResponse` gained `blocking_questions: tuple[str,
...] = ()` (mirrored into `MockExecutor`/`RealExecutor`, same pattern as
T7.1's `high_severity_findings`) — the analyst profile's own output contract
already documented this field back in T4.2, anticipating this task.
`audit/decisions_log.py` (new) — `append_decision`/`read_decisions`/
`next_decision_id`, mirroring `approvals_log.py`'s exact shape, backing
`decisions.jsonl` (C10-AC6's `Decision` model already existed, unused until
now). `GraphState` gained `clarification_answer` (the human's answer text,
threaded into S1's re-run prompt).

`engine/fsm.py`'s `_record_batch_result` gained an `is_s1_clarification`
check alongside T7.1's `is_s7b_findings` one: S1 passing with non-empty
`blocking_questions` sets `pending_checkpoint = CLARIFICATION` (S1's own
`StageSpec.checkpoint_after` stays `None` — the same dynamic-override
reasoning as S6's Change-control, T6.2). `resolve_checkpoint` gained an
`ApprovalDecision.ANSWER` + `CLARIFICATION` branch: stores the answer on
`graph_state.clarification_answer`, calls `engine/replanning.invalidate_from(
graph_state, StageId.S1_REQUIREMENTS)` (reusing T7.2's exact mechanism — S1
and everything downstream, since nothing past S1 can be trusted until its
questions are resolved), records a `Decision` to `decisions.jsonl` (not just
`approvals.jsonl` — C10-AC6's literal requirement), and a `retry` event
naming the trigger. `_build_request`'s new `_rendered_prompt_for` helper
appends the stored answer to S1's prompt on re-run — the minimum viable form
of "available to the analyst profile as context," matching how every other
stage's prompt is still just a placeholder string (real profile-rendered
prompts aren't wired into `engine/fsm.py` at all yet, unrelated to this task).

**Two real bugs this task's own test caught, both now shared fixes:**
1. `invalidate_from` (T7.2) reset the *triggering* stage's own attempt count
   to 0, not just the genuinely-downstream stages' — meaning a re-run replayed
   attempt 1's exact mock fixture again (the same `blocking_questions`, in
   this task's case; the same design output in T7.2's), never able to
   represent "this attempt is different because of the feedback/answer."
   Fixed: the triggering stage keeps its own attempt count (so a re-run is a
   real next attempt); only strictly-downstream stages reset to 0.
   T7.2's own test needed a one-line update (`attempts == 2`, not `1`) since
   this changes its observed behavior too, correctly.
2. That fix meant a re-run's now-higher attempt number (e.g. S3's 2nd
   attempt) needed its own mock fixture, which most scenarios' generic
   fallback never provided (only attempt 1 got the bare-`{stage}.json`
   fallback). Fixed in `executors/mock.py`: the bare-name fixture is now a
   fallback for **any** attempt, not just the first — a per-attempt fixture
   still takes priority when one exists (T7.1's retry tests, which rely on
   attempt 2 finding *nothing* or finding an explicit `S6-2.json`, are
   unaffected either way).

**Covered:** C7 (Clarification checkpoint); C10-AC6.

**Tests:** `tests/unit/engine/test_fsm.py`'s
`test_s1_blocking_questions_pause_for_clarification_then_answer_reruns_s1` —
S1's fixture carries `blocking_questions` -> pauses at Clarification (not
Design) -> `answer` records the decision in `decisions.jsonl` (stage/actor/
choice asserted) and invalidates S1 -> a further `drive()` call re-runs S1
(attempt 2, a *different*, clean fixture) then proceeds through S2 to the
real Design pause, proving downstream continues normally. A second test
confirms S1 with no blocking questions never pauses. `executors/mock.py`
gained its own direct test of the any-attempt bare-name fallback. Full gate:
221 tests, 97.07% coverage.

**Deferred / assumed:**
- Same real-config-loading gap as T7.3's `inject_fault`: no CLI command loads
  a scenario's real inputs from `.orchestrator/scenarios/<id>.toml` yet —
  that's a separate, larger, pre-existing integration gap, not this task's.
- The answer is appended to S1's prompt as plain text, not run through any
  real prompt-templating/profile-rendering system — none exists in
  `engine/fsm.py` yet for *any* stage, first-run or re-run alike.

## T8.1 — Traceability + decision lineage

**What changed:**
- **Citation convention (new, this task's own design decision — requirements.md
  doesn't dictate one):** a top-level `## <ID>` heading followed by a `Cites:
  <ID>[, <ID>...]` line, before the next such heading. Used in
  `01-requirements.md` (`## FR-n` cites `REQ-n`) and `02-design.md` (`## DD-n`
  cites one or more `FR-n`). `03-plan.md` needed no new syntax — its existing
  shape (`## FR-n` heading, `- T-n.n (DD-n): ...` task lines nested under it)
  already encodes both facts C10-AC1 asks for a task to have (cites a DD,
  sits under an FR), just via nesting + an inline parenthetical instead of a
  `Cites:` line.
- `gates/traceability_gate.py` (new): `RequirementsCitationGate`,
  `DesignCitationGate`, `PlanCitationGate` — one focused, independently
  testable gate class per file, each reading only its own stage's deliverable.
  **Wired live** into `engine/fsm.py`'s `_gates_for` as S1/S3/S4's exit gates
  — the first genuinely real (non-stub) gates in the codebase. Wiring them
  meant updating `fixtures/mock/_generic/{S1,S3}.json` (added `Cites:` lines;
  `S4.json` already matched) and one custom fixture set in
  `tests/unit/engine/test_fsm.py`'s T7.4 test — confirmed to be the *only*
  other place with custom S1/S3 fixture content before making this live.
- **Commit trailers (C10-AC2, G-13):** `engine/runner.py` gained
  `CommitTrailerContext`/`commit_message_with_trailers` — a structured
  trailer block (`Task`/`FR`/`Req` when known, `Run`/`Stage` always).
  `stage_commit_hook` (T6.1) and `engine/fsm.py`'s `_run_fix_call` (T7.1) both
  now build their commit messages through it — the fix-call commit carries
  `Stage: S5a-fix` specifically (not `S5a`), matching G-13's literal
  resolution text, so `git blame`/trailers can tell a retry fix from original
  implementation work at a glance.
- `audit/traceability.py` (new): `generate_traceability_report` assembles the
  FR -> AC -> DD -> task -> commit -> test chain from plain-text deliverable
  content + a commit list + acceptance-test-file content, rendering a markdown
  table plus a `## Gaps` section naming anything missing a link. Defines one
  more convention along the way: an acceptance test file is tagged with a
  `# Traces: FR-n.ACm[, ...]` comment line (matching requirements.md S5b's
  "each tagged with its FR-n.ACm" — no tagging mechanism existed before this).
  `backward_trace` walks one commit's own `Task:` trailer back to its FR (via
  `03-plan.md`'s nesting) and REQ (via `01-requirements.md`'s `Cites:` line) —
  C10-AC5's "commit trailer -> task -> FR -> REQ" half (the `git blame ->
  trailer` half is the caller's job, outside this module).
- `decisions.jsonl` (also named in this task's own goal text): already built
  in T7.4 (`audit/decisions_log.py`), ahead of this task needing it for the
  Clarification checkpoint's answer recording — nothing further needed here.

**Not done — a deliberate, documented scope boundary:** requirements.md's own
stage table has a distinct "Join S7" row ("traceability.md generated (->
workspace)"), but the current fixed graph (`models/graph.py`'s `StageId`) has
no node for it at all — S8 simply depends on both S7a and S7b directly
(T6.1's parallel-join change). Actually wiring `generate_traceability_report`
to run automatically and write `traceability.md` to the workspace at a real
"Join S7" point would mean adding an entirely new stage to the fixed
nine-stage (now effectively eleven-node) graph — a graph-topology change well
beyond this task's own scope. What's built is the generator itself, fully
tested against constructed inputs, ready to be called from wherever that
future integration lands.

**Covered:** C10-AC1, C10-AC2, C10-AC3, C10-AC5 (AC4 — "00-source.md hash
matches" — and AC6 — decision fields — predate/are outside this task).

**Tests:** `tests/unit/gates/test_traceability_gate.py` (9 tests: each gate's
pass + fail + missing-file cases). `tests/unit/engine/test_runner.py` gained
4 tests for the trailer helper + `stage_commit_hook`'s real trailer output
(via an actual git repo, checked with `git log --format="%(trailers)"`, the
same verification convention already used for every commit this session).
`tests/unit/audit/test_traceability.py` (7 tests): a complete synthetic chain
reports no gaps (C10-AC3's literal DoD wording); each individual missing
link (no AC, no DD, no task, no commit, no test) is reported by name; the
backward-trace test walks a real commit -> task -> FR -> REQ (C10-AC5's DoD),
plus unknown-commit and no-task-trailer edge cases. Full gate: 240 tests,
97.17% coverage.

**Deferred / assumed:**
- Real per-task S5a commits (which would populate `Task`/`FR`/`Req` trailers
  on ordinary S5a work, not just fix-call commits) still don't exist — S5a is
  still one generic call per stage, not one call per plan task. This task's
  trailer support is ready for that; it doesn't build it.
- No CLI command calls `generate_traceability_report` or writes
  `traceability.md` anywhere yet — consistent with the "Join S7 doesn't exist
  as a stage" boundary above.

## T8.2 — Metrics + reporting

**What changed:**
- **Prerequisite bug found while designing this task (C13-AC1):**
  `metrics.json` must be "computed from events only," but reaching
  `RunState.COMPLETED` or `RunState.REJECTED` emitted *no event at all* —
  only `STOPPED`/`FAILED` did (via the pre-existing `stop` event from
  safe-stop/fallback-to-human). A run's own success/failure was therefore
  undecidable from `events.jsonl` alone, contradicting the very AC this task
  exists to satisfy. Fixed first: `EventType` gained `RUN_TERMINAL =
  "run_terminal"`; `engine/fsm.py` gained `_record_run_terminal` (appends the
  event) and `_complete_and_record` (wraps `_complete_if_all_stages_passed`,
  emitting the event only on an actual None -> COMPLETED transition, keyed
  off "was `terminal_state` still `None` before the call"). All 3 raw
  `_complete_if_all_stages_passed(...)` call sites now go through
  `_complete_and_record(...)` instead; `resolve_checkpoint`'s `REJECT_FINAL`
  branch calls `_record_run_terminal(..., RunState.REJECTED)` directly right
  after setting `terminal_state`. Every terminal state now has exactly one
  event that names it — `stop` for STOPPED/FAILED, `run_terminal` for
  COMPLETED/REJECTED.
- `audit/event_log.py` gained a module-level `read_events(path) -> list[Event]`
  (mirrors `approvals_log.read_approvals`/`decisions_log.read_decisions` —
  empty list for a missing file, one `Event.model_validate_json` per line)
  and `EventLog.read_all()` as a thin instance-method wrapper over it, so
  metrics/report code can read a finished run's log without needing to
  construct an `EventLog` purely to read (it only ever appends otherwise).
- `audit/metrics.py` (new): `compute_metrics(events: list[Event]) -> Metrics`,
  pure and computed from `events` alone (C13-AC1), covering every C13 figure:
  - `run_success`: `True`/`False`/`None` (no terminal event yet) from the
    first `run_terminal`/`stop` event seen.
  - `stage_first_pass_rate`: fraction of stages whose `attempt == 1` call
    passed, over every stage with a first attempt recorded.
  - `retry_count`/`rollback_count`: straight counts of `retry`/`rollback`
    events.
  - `mttr_seconds`: mean, over every stage that both failed and later
    recovered, of (next success's finish time) - (first failure's finish
    time); `None` if no stage did both.
  - `end_to_end_latency_seconds`: last event's timestamp minus the first's.
  - `human_wait_seconds`: sum of every `approval_requested` -> next
    `approval_recorded` gap.
  - `end_to_end_latency_excluding_human_wait_seconds`: the above two,
    subtracted — C13's "with and without human wait" pair.
  - `stage_latency_seconds` / `agent_call_latency_seconds`: built from pairing
    every `stage_started`/`stage_finished` by `(stage, attempt)`. One such
    pair *is* one agent call (`StageRunner.run()` makes exactly one executor
    call per invocation, `engine/runner.py`) — so `agent_call_latency_seconds`
    is keyed `"{stage}:{attempt}"` per call, and `stage_latency_seconds` is
    that stage's attempts summed (its total wall-clock cost across every
    retry, not just the winning attempt). This is a judgment call: C13 lists
    "stage and agent-call latency" as one bullet without defining the
    difference between the two; treating agent-call as the atomic per-attempt
    figure and stage as its sum is the only reading consistent with how the
    codebase actually structures one call per attempt.
  - `metrics_to_model(Metrics) -> MetricsModel`: the pydantic-model bridge
    `audit/run_record.py`'s `atomic_write_json` needs (it requires a
    `BaseModel`; `Metrics` itself is a plain frozen dataclass, kept that way
    so the computation functions stay pydantic-free).
- `audit/report.py` (new): `generate_report(GraphState, Metrics) -> str` — a
  markdown `report.md`: run ID/scenario/outcome, a per-stage status/attempts/
  commits table (from `GraphState.stages`, no event parsing needed here),
  and a metrics table.
- `audit/pr_description.py` (new): `generate_pr_description(GraphState,
  run_record_location, audit_repo_url=None) -> str` — C12-AC5's literal ask:
  identifies the run by ID and names its record's location; adds an audit-repo
  link only when one is given (AC4/AC5's central-repo publishing is itself a
  SHOULD, not built yet, so the link is optional input, not a hard dependency).
  Lists every commit the run made (from `GraphState.stages`, same source as
  the report).

**Not done — deliberately, matching this task's own DoD:** no CLI/`drive()`
wiring writes `metrics.json`/`report.md`/`pr-description.md` to a run
directory yet. The DoD asked for computation "from a scripted synthetic
`events.jsonl`," not for a write-to-run-folder integration; `run.json`
creation itself is still the pre-existing, separately-tracked deferred item
(`engine/fsm.py`'s own module docstring). These three modules are the pure,
fully-tested generators, ready for whichever future task wires them to a
real run's files.

**Covered:** C13, C13-AC1, C12-AC5.

**Tests:** `tests/unit/audit/test_metrics.py` (7 tests) — the DoD's own
scripted scenario (S1 passes first try; S2 fails then passes on retry, with
a `retry` event in between; a Change-control approval blocks for 60s; S3
passes first try; the run completes), built through a real `EventLog` (not
hand-built `Event` objects) so the test exercises the same hash-chained
read path metrics will actually see, asserting every one of C13's figures
against hand-computed expected values (`mttr_seconds == 20.0`,
`stage_first_pass_rate == 2/3`, `human_wait_seconds == 60.0`, etc.); plus a
no-events-at-all case (everything `None`/zero, nothing raises), a
`stop`-event-means-failure case, a rollback-count case, and a
`metrics_to_model` round-trip case. `tests/unit/audit/test_report.py` (4
tests) and `tests/unit/audit/test_pr_description.py` (5 tests) cover their
respective generators' key content (identity, per-stage rows, the
metrics/commits sections, the optional audit-repo link). `tests/unit/audit/
test_event_log.py` gained 2 tests for `read_all`/`read_events`.
`tests/unit/engine/test_fsm.py` gained 2 tests proving `run_terminal` is
actually recorded (once for COMPLETED, once for REJECTED) — the prerequisite
fix this task started with. Full gate: 257 tests, 97.35% coverage.

**Deferred / assumed:**
- Writing `metrics.json`/`report.md`/`pr-description.md` into a run's own
  directory (and generating them automatically at run-completion time) is
  not wired anywhere yet — see "Not done" above.
- `audit_repo_url`/central-audit-repo publishing (C12-AC4) doesn't exist as a
  real capability anywhere in the codebase yet; `pr_description.py`'s param
  for it is accordingly optional, not backed by a real publisher.

## T9 — Coverage / gap-filling pass

**What changed:** nothing — verification only. `scripts/check.py`'s pytest gate
was already passing at 97.35% coverage (257 tests) immediately after T8.2,
well above C15/`pyproject.toml`'s 85% `fail_under`; ruff, mypy --strict, and
pip-audit are all green. Re-ran `pytest --cov=orchestrator --cov-report=
term-missing` and checked every file below 100%: the lowest are
`cli/commands/run.py` (67%) and `cli/commands/_common.py` (76%) — not an
actual gap, just a coverage-tool artifact: `tests/integration/
test_pause_resume.py` exercises the full CLI (`run`/`approve`/`reject`/
`answer`/`stop`) via `subprocess.run([sys.executable, "-m",
"orchestrator", ...])` (C15-AC1's "tests run entirely on the mock
executor" is satisfied there too — always `--mock`), so `coverage.py`'s
in-process instrumentation never sees those lines execute, even though
they're genuinely covered by a real end-to-end test. No new tests added;
nothing to fix.

**Found while verifying, not fixed (flagging for the hard-stop review before
T10):** `cli/commands/run.py` still hard-refuses anything but `--mock`
("real executor not available yet (T4) - pass --mock", `handle()` line 51)
even though T4.1/T4.2 (real executor + 7 agent profiles) are both long since
built and tested (`executors/real.py`, `agents/profiles/*.toml`). No CLI
command anywhere constructs a `RealExecutor` — `run.py`/`approve.py`/
`reject.py`/`answer.py` all hardcode `MockExecutor(FIXTURES_ROOT)`. T10's own
task text never says the three showcase runs must go through this CLI
specifically ("real-executor run of the ... scenario end to end" — the how
isn't specified), so this may be intentional (T10 might drive `RealExecutor`
directly via a script, bypassing the CLI layer entirely) rather than a bug —
but if the intent is to run the showcases via `orchestrator run --real
...`, that flag doesn't exist yet and would need building first. Left
exactly as found; not this task's call to make silently.

**Covered:** C15-AC1, C15-AC2 (already satisfied by T1–T8's own tests; T9
added no new coverage).

## T9.5 — Pre-T10 integration audit (5 commits)

User-directed pass, before authorizing T10's real showcase runs: "showcase
runs MUST go through the CLI." Wire the real executor into the CLI (item 1);
audit every built capability against the real CLI run path and wire what's
built-but-unwired (item 2); an end-to-end CLI test proving the artifacts
exist (item 3); confirm ORCH_HOME and per-call budget/timeout (item 4).

**What five commits changed, in order:**
1. `3ec1fe3` — S0/S6/S8 made real orchestrator-only stages
   (`StageSpec.requires_agent`), real per-stage prompts, the S6 command gate
   (`gates/command_gate.py`), the 8th C6 policy (`dependency_control`),
   config-driven per-call timeout/budget, and terminal-time metrics.json/
   report.md/pr-description.md/traceability.md generation.
2. `008cd7b` — analyst/architect/planner/test_engineer profiles taught T8.1's
   citation format (they predated it and would have failed their own gates).
3. `1a90cb2` — the CLI itself: real executor by default, `--mock` opt-in,
   run.json, executor/target persistence across approve/reject/answer.
4. `cc22d38` — the end-to-end CLI artifact test.
5. `54a57a5` — the missing `orchestrator rollback` command.

### Integration audit table

Every capability the user's item 2 named, plus everything else found while
tracing the real CLI run path end to end. **Wired** = reachable from a real
`orchestrator run`/`approve`/`reject`/`answer` invocation as of this pass.

| Capability | Built (task) | Wired on the CLI path? |
|---|---|---|
| 7 (now 8) C6 policies | T6.2 (7), T9.5 (dependency_control, 8th) | **Yes** — `cli/commands/_common.py:policies_for()`, every command that calls `drive()` |
| S6 command gate (tests + coverage ≥ 85%, D-11/AC5) | T9.5 (new — was fully unbuilt) | **Yes** — `gates/command_gate.py:TestCoverageGate`, S6's exit gate |
| Traceability gates (S1/S3/S4 citation) | T8.1 | **Yes** (already wired T8.1) — **but the profiles that produce the cited files predated the convention and would have failed the gate on a real call**; fixed this pass (commit 2) |
| Clarification checkpoint trigger | T7.4 | **Yes** — always active in `_record_batch_result`, no config needed |
| Change-control checkpoint trigger | T6.2 | **Yes** — `_evaluate_s6_policies`, runs whenever `policies` is non-empty, which every CLI command now guarantees |
| Fault-injection flag (G-16) | T7.3 | **Yes** — but not a CLI flag: scenario-config-driven (`.orchestrator/scenarios/<id>.toml`'s `inject_fault`, T5.3), resolved by `resolve_new_run_inputs` into `DriveRequest.inject_fault`. Matches G-16's own design (a property of the scenario, not an operator toggle) |
| Bounded retries (invalid-output/S6/S7b, C9) | T7.1 | **Yes** — `ReliabilityLimits.retry_limits`, now sourced from `config/defaults.toml` (was a hardcoded fallback before this pass) |
| Rollback (G-14) | T7.1 (`rollback_to_checkpoint`) | **Fixed this pass** — no `orchestrator rollback` command existed; added (commit 5) |
| Per-call timeout / budget cap | T2.1 (hardcoded) | **Fixed this pass** — `Limits.per_call_timeout_seconds`/new `Limits.max_call_budget_usd` in `config/defaults.toml`, threaded through `ReliabilityLimits` into every real agent call's `timeout_seconds`/`--max-budget-usd` |
| Parallel S5/S7 scheduler | T6.1 | **Yes** — structural (`engine/scheduler.py`'s `run_batch`), fires automatically whenever a batch has 2 ready siblings; no separate wiring needed |
| `traceability.md` (C10-AC3) | T8.1 (generator) | **Fixed this pass** — written into the workspace at COMPLETED (`engine/fsm.py:_write_traceability`) |
| `metrics.json` (C13-AC1) | T8.2 (generator) | **Fixed this pass** — written into the run directory at every terminal transition, whatever the outcome (`_write_metrics_json`) |
| `report.md` | T8.2 (generator) | **Fixed this pass** — written at S8, before the Release checkpoint pause, so the approving human can read it (`_s8_commit_hook`) |
| `pr-description.md` (C12-AC5) | T8.2 (generator) | **Fixed this pass** — same S8 commit hook |
| Push after Release approval (C14-AC1) | **Not built at all before this pass** | **Fixed this pass** — `git_ops`-level `git push origin run/<id>`, gated on `terminal_state is COMPLETED` (`cli/commands/_common.py:push_if_completed`), which never happens without Release approval since S8's checkpoint is unconditional |
| Real per-stage agent prompts | **Not built** — every stage got the literal string `"stage S1"` | **Fixed this pass** — `_STAGE_TASKS` + S1's own requirement-text prompt |
| Real workspace prepare (template copy / clone at base_ref) | T5.1/T5.2 (template, target repos) | **Fixed this pass** — `workspace/manager.py`'s functions existed but were never called from `drive()`; S0's own commit hook now does the real prepare directly (couldn't reuse `manager.py` as-is — see its own docstring note on commit timing) |
| Workspace venv creation (C3-AC3) | Deferred at T5.1 ("needed at T10") | **Fixed this pass** — S0's commit hook also creates `.venv` + `pip install -e ".[dev]"`, best-effort |
| run.json creation (C1-AC2) | **Not built at all before this pass** | **Fixed this pass** — `cli/commands/_common.py:record_run`, called after every `drive()`/`resolve_checkpoint()`-driven state change |
| Executor persistence across resume | N/A (real executor had no CLI path before this pass) | **Fixed this pass** — `GraphState.executor_kind`, set once, read back via `engine.fsm.load_graph_state` |

### Found, flagged, deliberately **not** fixed this pass

- **Flat vs. nested requirement-folder convention.** requirements.md §11
  nests every deliverable under `docs/requirements/<REQ-id>-<slug>/`; every
  piece of code that reads/writes these files (gates, `audit/traceability.py`,
  every fixture, every profile) uses flat workspace-root filenames instead —
  predates this task. Renaming now would touch dozens of already-tested files
  for a concern orthogonal to "wire the real executor"; kept flat everywhere,
  consistently, rather than fixing half of it. (`engine/fsm.py`'s own module
  docstring carries this note too, for anyone reading the code directly.)
- **Conditional S2 (§10's "stage graph with conditional S2").** Verified live
  (greenfield end-to-end run, this pass's own manual check): S2 (codebase
  analysis) runs unconditionally, even for a greenfield run with nothing to
  analyze. No skip-S2-for-greenfield logic exists anywhere in `engine/graph.py`
  or `engine/fsm.py`. Harmless today (S2's mock/real output is just generically
  ignored downstream) but a real S2 call under the real executor would burn an
  agent call for nothing on every greenfield run. Graph-topology-adjacent
  change, same category as T8.1's already-documented "Join S7 doesn't exist as
  a stage" boundary — a follow-up task, not squeezed into this one.
- **Lint/types/security/dependency-audit as separate S6 command gates.** §7's
  S6 row names all five; this pass's `TestCoverageGate` covers all five in
  practice (it runs the *whole* `scripts/check.py`, not just pytest) for any
  workspace built from the T5.1 template or either registered target repo —
  but that's a documented reliance on convention, not five independently
  configurable gates. Flagged, not rebuilt as five separate things: no target
  repo in this project needs anything more granular yet.
- **Central audit-repo publishing (C12-AC4).** Explicitly a SHOULD, not MUST;
  no publisher exists anywhere in the codebase. `pr_description.py`'s
  `audit_repo_url` param stays optional, unbacked.
- **Per-task S5a commits/looping.** Still one generic call per stage (T8.1's
  own documented limitation, reconfirmed here) — the real per-stage prompt
  added this pass explicitly tells the agent to implement every task in one
  call, an honest instruction matching current reality rather than the
  developer profile's own (aspirational) "exactly one task per call" persona
  text.
- **`target_repo_url` as a real remote URL, not just a local path.** Every
  actual usage in this project (T5.2's two registered projects) is a local
  filesystem path; `Path(target_repo_url)` wrapping (used for `clone_repo`/
  `git remote add origin`) is untested against a genuine `https://` URL on
  Windows and may not round-trip cleanly. Not a blocker for T10 (both real
  scenarios use local paths) but worth knowing before ever pointing this at a
  bare GitHub URL directly.

### Live verification (this pass, not part of the pytest suite)

A real local target repo (registered project, `.orchestrator/scenarios/
greenfield.toml` + `.orchestrator/project.toml`, mirroring T5.2/T5.3's real
ones) driven through `build_new_run_request` + `drive()` with `MockExecutor`
(so no real `claude -p` calls, matching C15-AC1, while every *orchestrator*-
side piece — S0's real prepare, the venv, the command gate wiring — runs for
real): confirmed the workspace was copied from `templates/python-service/`,
`.venv` exists with a real interpreter, `scripts/check.py` is present (so
`TestCoverageGate` will actually run something on a genuine T10.1 attempt),
and `00-source.md` contains the scenario's real requirement text, not a
placeholder. The full CLI round trip (register → run → approve × 2) was also
re-run manually end to end, confirming `metrics.json`/`report.md`/
`pr-description.md`/`traceability.md` all land in the right places with real
content (not just under the automated E2E test).

**Full gate at the end of this pass:** 272 tests, 95.84% coverage; ruff,
mypy --strict, pip-audit all clean.

## T9.7 — Findings from the first real greenfield run (7 items, 8 commits)

The first real showcase run (`greenfield-minimal-20260930-001`, driven by the
user through the CLI per T9.5) failed after the user rejected the design at
the Design checkpoint. User-directed pass, from the run record's own findings:
fix all seven, add tests, keep the full gate green, verify only against
throwaway local repos (never the two registered target repos), and report
back the root cause of item 4 rather than starting another run.

**What eight commits changed, in order:**
1. `65dd501` — `workspace/git_ops.py:read_file_at_commit` was silently
   stripping a file's trailing newline (it shared `run_git`'s blanket
   `.strip()`, correct for SHA/porcelain output but wrong for file content) —
   found while building item 4's gate, since it made a byte-identical file
   compare as "changed" in one direction and could mask a real change in the
   other.
2. `c75e162` — `gates/unchanged_on_retry_gate.py`: new `UnchangedOnRetryGate`,
   S3's exit gate — fails a retry attempt whose `02-design.md` is still
   byte-for-byte what HEAD already had, with a clear reason.
3. `bbf4ff3` — `gates/technology_stack_gate.py`: new `TechnologyStackGate`
   (item 6c) requiring a `## Technology stack` section naming a language
   consistent with the target; two new rules on `agents/profiles/
   architect.toml` (item 6a: mandate the section; also mandate that a
   rejection actually gets addressed, not resubmitted unchanged).
4. `adf9550` — the core fix, item 4's real root cause (below) plus items 1/5/
   6b: `GraphState.retry_cycle_start_attempts` (fresh bounded-retry budget
   per re-plan cycle, item 1) and `GraphState.design_rejection_feedback`
   (item 5 — the rejection comment now actually reaches S3's re-run prompt);
   `resolve_checkpoint`'s REJECT+DESIGN branch now records a `Decision` too
   (previously only Clarification answers did); S3 wired to
   `TechnologyStackGate`/`UnchangedOnRetryGate`; `_technology_stack_
   instruction` adds the target's real stack (from `workspace/pyproject.
   toml`) to S3's prompt (item 6b).
5. `6ce0676` — `gates/traceability_gate.py`: FR/DD heading regexes now accept
   a title after the ID (`## DD-1: <title>`, the real agent-produced format —
   only a bare `## DD-1` matched before, so every citation gate passed
   vacuously, "0 DD(s) cite an FR", on the real failed run's own files, item
   2); `DesignCitationGate` now fails on zero DD sections found, and on any
   FR not covered by ≥1 DD (S3's own documented exit condition).
6. `85ec02f` — `engine/runner.py`: a gate failure now still records
   `stage_finished` (previously only `gate_result`, so a gate-failed stage
   was invisible in `stage_finished` terms); every `stage_finished` payload
   now carries `outcome`/`error` regardless of cause.
7. `ce0e18e` — item 3: new `AgentCallTranscript` model + `audit/
   agent_transcripts.py`; every real agent call (`StageRunner` and the
   per-task S5a runner, both via a new `StageRunnerOptions` bundle keeping
   their constructors under the 5-arg limit) writes `agents/<agent_call_id>.
   json` (role, profile version hash, prompt, response); every event now
   carries that same `agent_call_id`.
8. `91be387` — item 7: `record_run` also writes `scenario.json` (C2-AC2) and
   `config.effective.json` (D-7), each hashed with the hash stored on
   `run.json`; every real agent-backed stage's output files get a
   content-hashed copy under `artifacts/<stage>/`; `orchestrator run --mock`
   now resolves a real registered target's scenario config when one exists,
   so `req_id`/scenario snapshot are populated the same as a real run without
   touching the real Claude/network path; the E2E CLI test extended to drive
   a full run (including a Design rejection + re-approval) against a
   throwaway local target and assert every file §11 promises. Also found and
   fixed in this commit: `_write_json_snapshot`'s `write_text()` silently
   rewrote `\n` to `\r\n` on Windows, so a hash computed before the write
   never matched the file a later reader hashed back — fixed by hashing the
   exact bytes written via `write_bytes()`.

### Item 4's root cause

All of S3's re-run gates passed on the failed run, yet the stage still
finished failed ~30 seconds in, and the post-rejection `02-design.md` was
byte-for-byte the original (still TypeScript-style sketches, no tech stack).
Tracing it: `resolve_checkpoint`'s REJECT+DESIGN branch invalidated S3
onward and let `drive()`'s normal batch-selection re-run it, but never
persisted the rejection comment anywhere `_rendered_prompt_for` could see —
unlike the Clarification-answer branch, which does persist `graph_state.
clarification_answer` for exactly this reason. So S3's second attempt
received the *exact same prompt* as its first, with zero signal that
anything needed to change; the agent (real or, in the showcase run, whatever
was standing in for it) had no reason to produce different output, and
didn't. Compounding it: item 1's bug meant the stage's bounded-retry
threshold was computed from its *cumulative* attempt count, not attempts
*since the last re-plan* — so a rejection landing on a stage already near its
retry ceiling had little or no real budget left, and the one failure ended
the run. Fixed by `design_rejection_feedback` (persisted, injected into S3's
next prompt) plus `retry_cycle_start_attempts` (a fresh budget every re-plan
cycle) — commit `adf9550`. `UnchangedOnRetryGate` (commit `c75e162`) is the
independent safety net: even if a future prompt-plumbing bug reintroduces
this failure mode, a retry that leaves the file unchanged now fails loudly,
with a clear reason, instead of silently passing every gate and dying with
no diagnosable cause.

### Verification

Per the user's explicit instruction, no verification touched either
registered target repo (`shortener-greenfield-by-agents`,
`url-shortener-brownfield-target`) — every test uses `tmp_path`-based
throwaway local repos, including the new E2E CLI test's throwaway
existing-codebase target (`.orchestrator/project.toml` + `.orchestrator/
scenarios/<id>.toml` under `tmp_path`, never a registered project).

**Full gate at the end of this pass:** 324 tests, 96.22% coverage; ruff,
mypy --strict, pip-audit all clean.

