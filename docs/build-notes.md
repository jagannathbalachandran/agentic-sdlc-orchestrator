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

