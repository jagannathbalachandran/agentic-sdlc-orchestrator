# Build tasks — Phase 1 vertical slice

Expands `docs/architecture-proposal.md` §4.1 into concrete, ordered tasks. Each parent
block (P0, T1–T12) is the corresponding row in that section; sub-tasks (T1.1, T1.2, ...)
are what actually gets built, in build order. Capability/AC IDs and gap IDs (G-n) refer
to `docs/requirements.md` and `docs/architecture-proposal.md` respectively.

## Execution notes (governs every task below)

- Stay within the task's stated scope. If a task needs something outside it, or
  contradicts `docs/architecture-proposal.md`, **stop and ask** rather than improvise.
- Every task ships tests covering its listed AC(s), including edge/failure cases, and
  ends with `python scripts/check.py` green (ruff, ruff format, mypy --strict, pytest +
  coverage, pip-audit) before moving on.
- Commit per task, trailers `Task: <id>` plus the capability IDs it closes.
- Append a short entry to `docs/build-notes.md` per task: what changed, ACs covered,
  anything deferred or assumed.
- **Hard stops for review:** (a) after P0 + the ADR draft, (b) after T3, (c) before T10
  (the showcase runs). Do not proceed past these without explicit go-ahead.

---

## P0 — `claude -p` feasibility spike

**Goal:** confirm the CLI behavior O-4/O-6/O-10 depend on before building anything that
assumes it: JSON transport output, reliable tool-based file writes under an instructed
workspace path, a small trailing JSON summary, directory/tool restriction flags, and
system-prompt injection.
**Traces to:** validates O-4, O-6, O-10; feeds C8, C9-AC5.
**Constraints (from the reviewer):** scratch repo under `/tmp/spike-target` only; every
`claude -p` call driven from a Python script via `subprocess` with an explicit timeout;
capped with `--max-turns`; record exact commands, exit codes, output fields, and files
changed for each call; if a nested `claude` launch fails, record the error and the
workaround used.
**Files/modules:** none under `src/orchestrator/` — a standalone spike script (scratch
location) plus its output document.
**Dependencies:** none — first task.
**Definition of done:** `docs/spikes/claude-p-feasibility.md` written, containing the
recorded commands/exit codes/output fields/file diffs, and an explicit updated
Verified/Assumed status for O-4, O-6, and O-10. If a finding contradicts an assumption
already baked into `docs/architecture-proposal.md`, flag it plainly in the spike doc —
this is hard stop (a), together with the ADR draft.

---

## T1 — Foundations

### T1.1 Domain models
**Goal:** pydantic models for run/graph/event/decision/approval/agent-IO and the
config schemas (defaults/project/scenario).
**Traces to:** C2-AC2; groundwork for C5, C12-AC1.
**Files/modules:** `src/orchestrator/models/{run,graph,traceability,decisions,approvals,events,agent_io}.py`
**Dependencies:** none.
**DoD:** unit tests per model covering required fields, ID-format validation, and at
least one invalid-input case each; `scripts/check.py` green.

### T1.2 Config loader + `validate` (schema errors only)
**Goal:** `tomllib`-based loader for `config/defaults.toml`,
`.orchestrator/project.toml`, `.orchestrator/scenarios/*.toml`; `orchestrator validate`
CLI command reporting schema errors before any run (C1-AC1 as literally stated — no
hardening-merge logic; §9 stays COULD).
**Traces to:** C1-AC1, C2-AC1, C2-AC3.
**Files/modules:** `src/orchestrator/config/{loader,schema,validate}.py`;
`src/orchestrator/cli/commands/validate.py`; `config/defaults.toml` (new, minimal).
**Dependencies:** T1.1.
**DoD:** tests for valid config, missing required field, malformed TOML, and an
unregistered-project run attempt (C2-AC3); `scripts/check.py` green.

### T1.3 Hash-chained event log + atomic run-record I/O
**Goal:** `EventLog` (append + chain verify); atomic read/write for
`run.json`/`graph.json` (write-temp, `os.replace`).
**Traces to:** C12-AC1, C12-AC2, §11.
**Files/modules:** `src/orchestrator/audit/{event_log.py, run_record.py}`.
**Dependencies:** T1.1.
**DoD:** test proving chain verification detects a tampered/deleted event (C12-AC2);
test proving a simulated interrupted write never leaves a corrupt file; `scripts/check.py`
green.

### T1.4 Executor protocol + mock executor
**Goal:** `Executor` protocol; mock executor with fixture lookup by
`(scenario_id, stage_id, attempt)`, generic fallback for unmatched scenarios (closes
G-8), and file materialization from the fixture's `files` map into the workspace (O-4
revised, O-8).
**Traces to:** C8-AC1, C1-AC3, §13.
**Files/modules:** `src/orchestrator/executors/{base.py, mock.py}`; `fixtures/mock/`
(generic fallback fixtures for the orchestrator's own tests).
**Dependencies:** T1.1.
**DoD:** tests for a fixture hit, a fixture miss falling back to the generic set, and
file materialization actually writing the expected files into a tmp workspace;
`scripts/check.py` green.

---

## T2 — Engine walking skeleton

### T2.1 `StageSpec` + minimal static graph (S0, S1) + `StageRunner`
**Goal:** `StageSpec` model/registry; `graph.py` with S0 and S1 defined; `StageRunner`
implementing entry-gate → execute → exit-gate → policy (stub) → event → commit for one
stage at a time.
**Traces to:** C4-AC1, C4-AC4.
**Files/modules:** `src/orchestrator/engine/{graph.py, runner.py}`.
**Dependencies:** T1.3, T1.4.
**DoD:** unit test drives `StageRunner` through S0 then S1 on the mock executor,
asserting events recorded in order; `scripts/check.py` green.

### T2.2 Workspace manager
**Goal:** greenfield init (`git init` + setup commit, closes part of G-12), existing-repo
clone at base ref, venv creation, run-branch creation; `register` command backing.
**Traces to:** C1 (register), C3-AC1–AC5.
**Files/modules:** `src/orchestrator/workspace/{manager.py, git_ops.py}`;
`src/orchestrator/registry.py`.
**Dependencies:** T1.2.
**DoD:** tests against a throwaway local git repo (`tmp_path`) covering both greenfield
init and existing-repo clone, asserting the recorded base-ref/base-commit fields match
G-12's resolution; `scripts/check.py` green.

### T2.3 CLI entry + `run`/`register`/`validate`; pause/resume proven
**Goal:** `cli/main.py` dispatch; `engine.fsm.drive()` — the shared entry point every
run-touching command re-enters, rebuilding all state from disk (§3.2.1); prove the
reload mechanism by running S0 in one process and S1 in a second, separate process
invocation.
**Traces to:** C1-AC1/AC2 — **validates O-1/O-2's pause/resume design**.
**Files/modules:** `src/orchestrator/cli/{main.py, commands/{register.py, validate.py,
run.py}}`; `src/orchestrator/engine/{fsm.py, locking.py}`.
**Dependencies:** T2.1, T2.2, T1.2.
**DoD:** integration test spawning two separate CLI subprocess invocations (S0 then S1)
against a mock-executor greenfield scenario, asserting `graph.json` reflects both stages
complete after the second process exits; lock acquired at start and released at exit of
each; `scripts/check.py` green.

---

## T3 — Approvals + full graph

### T3.1 Approval checkpoints
**Goal:** `awaiting_approval` state; `approve`/`reject`/`answer`/`stop` commands; lock
staleness recovery (dead-PID or past-max-duration reclaim, closes G-2).
**Traces to:** C7-AC1–AC4, C1, closes G-1/G-2.
**Files/modules:** `src/orchestrator/engine/fsm.py` (extend); `src/orchestrator/cli/
commands/{approve.py, reject.py, answer.py, stop.py}`; `src/orchestrator/models/
approvals.py` (extend).
**Dependencies:** T2.3.
**DoD:** tests: pause at a stub checkpoint then resume via `approve` in a fresh process;
`reject` with feedback records an event and feedback; a stale-lock reclaim test
(simulated dead PID); `scripts/check.py` green.

### T3.2 Full S0–S8 graph, stub gates, Change-control + Release checkpoints
**Goal:** extend `graph.py` to all 9 stages with stub (schema-only) gates; wire
Change-control (conditional) and Release (always) approval checkpoints alongside
Clarification and Design.
**Traces to:** C4-AC3, C5-AC1–AC3, §7.
**Files/modules:** `src/orchestrator/engine/graph.py`; `src/orchestrator/stages/
s0_prepare.py` … `s8_release.py`; `src/orchestrator/gates/{schema_gate.py,
existence_gate.py, approval_gate.py}`.
**Dependencies:** T3.1, T1.1.
**DoD:** end-to-end mock-executor run through all 9 stages sequentially (no parallel
yet) reaching `completed`; every stage's entry/exit gate exercised at least once;
`scripts/check.py` green.

**— Hard stop (b): after T3. Review before continuing to T4. —**

---

## T4 — Real executor + agent profiles

### T4.1 Profile rendering + real executor
**Goal:** profile loader/render (O-10); real executor subprocess wrapper for
`claude -p` with directory/tool restriction (O-6) and a per-call timeout that kills
the **whole process tree** on expiry (Windows: `taskkill /T /F` against the child's
PID; POSIX: child launched in its own process group, group signaled), not just the
direct child (ADR-001); JSON-summary response parsing per the revised O-4 (agent
writes files via its own tools; response is `{summary, produced_ids,
files_written}`).
**Traces to:** C8-AC1–AC5, C9-AC5.
**Files/modules:** `src/orchestrator/executors/real.py`; `src/orchestrator/profiles/
{loader.py, render.py}`.
**Dependencies:** P0 (spike findings must inform the flags used here), T1.4, T3.2.
**DoD:** unit tests against a patched/fake subprocess covering: call exceeds
timeout → outcome `timeout`; malformed summary → retryable-error outcome; well-formed
summary → parsed `AgentCallResponse`. Plus two live tests: (1) a **live smoke call**
running S1 for real (`claude -p`) against a throwaway greenfield workspace, confirming
`01-requirements.md` lands at the expected path and the JSON summary parses; (2) a
**live timeout test** — launch a real call with a deliberately short timeout, confirm
the process tree is fully terminated (no lingering `claude`/child processes, checked
via the OS process list) and that no further file writes land in the workspace after
the timeout fires. Record both results in `docs/build-notes.md`. (Full
three-scenario real execution is still T10.) `scripts/check.py` green.

### T4.2 Agent profiles (7 roles)
**Goal:** author `agents/profiles/*.toml` for analyst, architect, planner, developer,
test engineer, technical writer, reviewer — each instructing tool-based writes + a
small JSON summary per O-4. Developer and test-engineer profiles get a scoped Bash
limited to running pytest, named via `--tools` under `--restricted` (ADR-001); every
other profile gets no Bash at all.
**Traces to:** C8-AC2/AC6.
**Files/modules:** `agents/profiles/*.toml`.
**Dependencies:** T4.1.
**DoD:** each profile validates against the profile schema from T1.1; developer and
test-engineer profiles assert a `Bash(pytest *)`-scoped tool allowlist, and every
other profile asserts no Bash entry present; `scripts/check.py` green.

---

## T5 — Greenfield template + target repo prep

### T5.1 Greenfield template
**Goal:** `templates/python-service/` scaffold — `src/` layout, CI workflow,
`.orchestrator/` example.
**Traces to:** §12 setup, C3-AC2.
**Files/modules:** `templates/python-service/**`.
**Dependencies:** T2.2.
**DoD:** copying the template and running its own CI-equivalent quality gates locally
succeeds on a fresh copy; `scripts/check.py` green (orchestrator's own).

### T5.2 Target repo prep — human-owned repo creation; Claude authors `.orchestrator/` only
**Goal:** two target repos exist and are registered: (1) `shortener-greenfield-by-agents`
— empty, only `.orchestrator/`; (2) `url-shortener-brownfield-target` — a **copy** of A1
(`url-shortener-ai-assisted`), tagged `baseline-greenfield`, used for both the brownfield
and ambiguous scenarios. **A1 itself is never modified, cloned into, or pushed to** —
the copy is a separate repo the user creates.
**Traces to:** §12, C3-AC4.
**Ownership:** creating both repos, producing the `url-shortener-brownfield-target` copy
of A1, and pushing the `baseline-greenfield` tag are **human-owned** — the user does
these. Claude's part is limited to authoring `.orchestrator/project.toml` in each repo
(once it exists), registering both projects via `orchestrator register`, and checking
whether `url-shortener-brownfield-target`'s test suite needs a running Postgres instance.
**Files/modules:** `.orchestrator/project.toml` authored in both target repos; no repo
creation, forking, copying, or pushing by Claude.
**Dependencies:** T5.1.
**DoD:** both target repos reachable via `orchestrator register`; `.orchestrator/
project.toml` present and valid in each; the Postgres finding (checked against
`url-shortener-brownfield-target`, not A1) and its mitigation recorded in
`docs/build-notes.md`.
**Stop condition:** pause and tell the user as soon as this task needs the repos to
exist (i.e. before anything that needs their URLs) — do not attempt to create, copy, or
tag them.

### T5.3 Scenario REQ text (B-1 + G-16)
**Goal:** author the three scenarios' REQ text — greenfield (project
`shortener-greenfield-by-agents`) broadened per B-1 (reject malformed input, unknown
code → 404, avoid code collisions); brownfield (project `url-shortener-brownfield-target`)
carrying the fault-injection flag (G-16); ambiguous (same project, "Links should
expire").
**Traces to:** B-1, G-16, §12.
**Files/modules:** `.orchestrator/scenarios/*.toml` in `shortener-greenfield-by-agents`
and `url-shortener-brownfield-target`.
**Dependencies:** T5.2.
**DoD:** `orchestrator validate` passes for each scenario file, project names matching
T5.2's repos; greenfield REQ text checked against B-1's three reliability behaviors
explicitly.

---

## T6 — Parallel join + policies

### T6.1 Parallel join (S5, S7)
**Goal:** threaded scheduler for S5a/S5b and S7a/S7b; serialized git-commit and
event-log writer so concurrent branches never race on the shared working tree or hash
chain (§3.2.2, closes G-3).
**Traces to:** C4-AC2, §7.3.
**Files/modules:** `src/orchestrator/engine/scheduler.py`; `src/orchestrator/workspace/
git_ops.py` (serialization lock).
**Dependencies:** T3.2, T2.2.
**DoD:** integration test running two mock-executor branches concurrently against a
real (`tmp_path`) git repo, asserting both file sets land and both commits succeed
without index corruption (closes O-5's validation step); `scripts/check.py` green.

### T6.2 Policies (7 of 8 — dependency control descoped) + Change-control checkpoint
**Goal:** implement workspace confinement, path partitioning, protected paths
(section-aware per G-4/G-5), main protection, secret scan (in-house regex, G-7), schema
change control, and diff-size limit. Dependency control is designed but not built this
slice (limitation). **Owns wiring the Change-control approval checkpoint** — the
natural home for it, since both trigger conditions (schema change control, diff-size
limit) are policies built in this same task. **Architectural note:** unlike Design/
Release, Change-control is *conditional* (C7), and `StageSpec.checkpoint_after` is a
static field set once at graph-definition time — it can't express "pause only if this
run's diff is risky." S6 needs a small extension to `_run_one_stage`'s (or an
S6-specific hook's) post-policy logic: after S6's policies run, if either flags the
diff, set `graph_state.pending_checkpoint = ApprovalCheckpointKind.CHANGE_CONTROL`
directly (bypassing `spec.checkpoint_after`, which stays `None` on S6's `StageSpec`) —
the same mechanism T7.4 needs for Clarification's conditional trigger, so build the
"dynamic pending_checkpoint override" as a small shared primitive both tasks call, not
duplicated logic.
**Traces to:** C6-AC1/AC2 for the 7 policies; C7 (Change-control checkpoint).
**Files/modules:** `src/orchestrator/policies/{base.py, workspace_confinement.py,
path_partitioning.py, protected_paths.py, main_protection.py, secret_scan.py,
schema_change_control.py, diff_size_limit.py}`; `src/orchestrator/stages/s6_verify.py`
(post-policy conditional pending_checkpoint); `src/orchestrator/engine/fsm.py` (the
shared dynamic-checkpoint primitive).
**Dependencies:** T6.1.
**DoD:** each policy has its own test proving detection and the specified outcome
(C6-AC1, literal requirement, so this is 7 separate tests minimum); **plus** a test
where a schema-change-control (or diff-size-limit) violation on S6's diff sets
`pending_checkpoint = CHANGE_CONTROL` and a clean diff does not; `scripts/check.py`
green.

---

## T7 — Reliability + re-planning

### T7.1 Bounded retries, rollback, safe-stop
**Goal:** invalid-output retry (max 2); S6-failure retry (max 3, one fix call per
attempt per G-13, commit trailer `Stage: S5a-fix` + affected `Task`/`FR`); S7b-findings
retry (max 2, invalidates S6/S7a/S7b per G-15); rollback to the last recorded checkpoint
commit (G-14); `stop` command; simple duration/call-count checks; fallback-to-human on
retry exhaustion.
**Traces to:** C9-AC1–AC3/AC5.
**Files/modules:** `src/orchestrator/engine/runner.py` (extend);
`src/orchestrator/engine/locking.py` (duration check); `src/orchestrator/workspace/
git_ops.py` (checkpoint recording + rollback).
**Dependencies:** T3.2, T6.1 (rollback needs checkpoint commits recorded by T6.1's
committing stages).
**DoD:** a test per bounded loop hitting its max and falling back to human with full
context; a rollback test asserting the workspace matches the last recorded checkpoint
exactly; `scripts/check.py` green.

### T7.2 Design-rejection re-planning
**Goal:** rejecting Design with feedback re-runs S3 then S4 onward; S1/S2 kept;
downstream stages marked `invalidated` (C11).
**Traces to:** C11-AC1–AC3. (Change-control/Release rejection re-planning — G-9's
broader extension — stays designed-only; limitation.)
**Files/modules:** `src/orchestrator/engine/replanning.py`.
**Dependencies:** T3.1.
**DoD:** test: reject Design checkpoint with feedback → S3 re-runs → S4 onward re-runs →
exit gates re-evaluated on the new output; `scripts/check.py` green.

### T7.3 Fault-injection hook (G-16)
**Goal:** when a scenario flags fault injection, the orchestrator (not an agent) writes
one failing acceptance test into `tests/acceptance/` immediately before S6's first
attempt for that run; the resulting event is recorded `injected: true`.
**Traces to:** G-16.
**Files/modules:** `src/orchestrator/stages/s6_verify.py` (or an `engine/runner.py`
hook); `src/orchestrator/audit/event_log.py` (injected flag).
**Dependencies:** T7.1.
**DoD:** test: scenario with the fault-injection flag set → S6 attempt 1 fails
deterministically on the injected test → `events.jsonl` shows `injected: true` on that
event → attempt 2 (after the S5a-fix call) passes; `scripts/check.py` green.

### T7.4 Clarification checkpoint (blocking questions → pause → `answer` re-runs S1)
**Goal:** **Owns wiring the Clarification approval checkpoint** — placed here, not
T4.1, because resuming it means *re-running S1 with the answers incorporated*, which
is structurally the same re-planning shape T7.2 already builds for Design rejection
(re-run a stage, keep what's upstream, mark downstream invalidated), not executor/
profile work. Depends on T4.1 existing first, since detecting "blocking questions"
needs S1's real output shape (the analyst profile's JSON summary carries a
`blocking_questions: list[str]` field when it has any). After S1 passes, if
`blocking_questions` is non-empty, use T6.2's shared dynamic-checkpoint primitive to
set `graph_state.pending_checkpoint = ApprovalCheckpointKind.CLARIFICATION` (S1's
`StageSpec.checkpoint_after` stays `None`, same reasoning as Change-control's
conditional trigger). `answer`'s decision and comment (the human's answers) are
recorded in `decisions.jsonl` as part of the run's decision lineage (C10-AC6), not
just `approvals.jsonl` — then S1 re-runs with the answers available to the analyst
profile as additional context.
**Traces to:** C7 (Clarification checkpoint); C10-AC6 (answers recorded in decision
lineage). **T10.3 (the ambiguous showcase) depends on this task** — it's the scenario
that exercises blocking questions → Clarification → answer.
**Files/modules:** `src/orchestrator/engine/replanning.py` (extend — the S1 re-run
path); `src/orchestrator/stages/s1_requirements.py` (conditional pending_checkpoint,
mirroring S6's change in T6.2); `src/orchestrator/audit/` (decision-lineage write on
`answer`).
**Dependencies:** T4.1 (real S1 output shape), T7.2 (shares the re-run-a-stage
mechanism), T6.2 (shares the dynamic-checkpoint primitive).
**DoD:** test: S1's output carries `blocking_questions` → run pauses with
`pending_checkpoint = CLARIFICATION` → `answer` records the answer in
`decisions.jsonl` → S1 re-runs (with the answers passed to the profile) → downstream
proceeds normally; a second test confirms S1 output with no blocking questions never
pauses; `scripts/check.py` green.

---

## T8 — Traceability, lineage, metrics, reporting

### T8.1 Traceability + decision lineage
**Goal:** citation gates (every FR cites the REQ, every DD cites ≥1 FR, every task
cites ≥1 DD); commit trailers including `S5a-fix` (G-13); `traceability.md` generated
at Join S7; `decisions.jsonl`.
**Traces to:** C10-AC1–AC6.
**Files/modules:** `src/orchestrator/gates/traceability_gate.py`;
`src/orchestrator/audit/traceability.py` (new); `src/orchestrator/models/decisions.py`
(extend).
**Dependencies:** T3.2, T6.1.
**DoD:** test asserting a synthetic run's `traceability.md` has no gaps
(FR → AC → DD → task → commit → test, C10-AC3); a backward-trace test (commit trailer →
task → FR → REQ, C10-AC5); `scripts/check.py` green.

### T8.2 Metrics + reporting
**Goal:** `metrics.json` computed from events only; `report.md`; `pr-description.md`
generation (identifying the run record per C12-AC5).
**Traces to:** C13-AC1, C12-AC5.
**Files/modules:** `src/orchestrator/audit/{metrics.py, report.py,
pr_description.py}`.
**Dependencies:** T8.1, T1.3.
**DoD:** test computing metrics from a scripted synthetic `events.jsonl` (including a
failure/retry/success sequence) and asserting the known success-rate/MTTR values;
`scripts/check.py` green.

---

## T9 — Coverage / gap-filling pass

**Goal:** close any coverage gaps left by T1–T8's incremental tests so the orchestrator's
own code reaches the 85% threshold — the same figure C15 states, `pyproject.toml`'s
`[tool.coverage.report] fail_under` sets, and `scripts/check.py` enforces explicitly via
`--cov-fail-under=85`.
**Traces to:** C15-AC1/AC2.
**Files/modules:** `tests/` — wherever `pytest --cov` reports gaps.
**Dependencies:** rolling; run after T8 as a dedicated pass.
**DoD:** `scripts/check.py`'s pytest gate passes at the enforced 85% threshold; ruff,
mypy --strict, and pip-audit all green.

**— Hard stop (c): before T10, the showcase runs. Review before continuing. —**

---

## T10 — Three showcase runs

Start T10.1 (greenfield) the moment T4.2, T5.3, T7.\*, and T8.\* are all done — don't
wait on anything else. Write T12 (documentation) *during* T10's wall-clock window, not
after it.

### T10.1 Greenfield showcase
**Goal:** real-executor run of the greenfield scenario end to end; derive mock fixtures
(D-21/O-8) from the transcripts; commit the run record to `evidence/runs/`.
**Traces to:** §12 greenfield row, D-21, C15.
**Files/modules:** `evidence/runs/<run-id>/**`; `fixtures/mock/<scenario>/**`.
**Dependencies:** T4.2, T5.3, T7.1–T7.3, T8.1–T8.2.
**DoD:** run reaches `completed` and the branch is pushed; run record committed;
fixtures derived and redacted per O-8; `docs/build-notes.md` entry written.

### T10.2 Brownfield showcase
**Goal:** real-executor run of the brownfield scenario against
`url-shortener-brownfield-target` at `baseline-greenfield` (never against A1 itself);
exercises the baseline check, impact analysis, FR-numbering continuation, migration →
Change-control approval, and the fault-injected S6→S5a retry (G-16).
**Traces to:** §12 brownfield row, C3-AC4, C6 (schema change control), C9 (retry).
**Files/modules:** `evidence/runs/<run-id>/**`.
**Dependencies:** T10.1 (pipeline proven once before repeating for real).
**DoD:** run reaches `completed`; Change-control approval exercised and recorded;
retry loop exercised with an `injected: true` event visible in `events.jsonl`; run
record committed.

### T10.3 Ambiguous showcase
**Goal:** real-executor run of the ambiguous scenario ("Links should expire") against
`url-shortener-brownfield-target` at `baseline-greenfield`; exercises blocking
questions → Clarification → answer, and Design rejection → re-plan.
**Traces to:** §12 ambiguous row, C7 (clarification), C11 (re-planning).
**Files/modules:** `evidence/runs/<run-id>/**`.
**Dependencies:** T10.1, **T7.4** (Clarification checkpoint — without it, S1's
blocking questions never pause the run, and this scenario's core demonstration
doesn't happen).
**DoD:** run reaches `completed`; the clarification answer is recorded in decision
lineage; Design rejection triggers re-planning per C11-AC1; run record committed.

**If a real run misbehaves:** report honestly what completed and what didn't — don't
let one bad run silently consume the time set aside for the other two (per
architecture-proposal.md §4.3).

---

## T11 — Final polish

**Goal:** `runs list`/`runs show` output formatting; final full `scripts/check.py` pass
across everything built.
**Traces to:** C1-AC4, C15.
**Files/modules:** `src/orchestrator/cli/commands/{runs_list.py, runs_show.py}`.
**Dependencies:** T10.1–T10.3, T12.1–T12.3.
**DoD:** `runs list`/`runs show` produce readable, correct output for all three showcase
runs; `scripts/check.py` green end to end, on the whole repo.

---

## T12 — Documentation (written during T10's wall-clock window)

### T12.1 README
**Goal:** extend the existing README (Setup section already added in T-01) with a
testing-approach section and pointers to the three scenarios.
**Files/modules:** `README.md`.
**Dependencies:** T8.
**DoD:** README covers setup, running the gates, testing approach, and how to run
`--mock` against the three showcase scenarios.

### T12.2 `docs/architecture.md`
**Goal:** the orchestrator's own architecture overview for the assignment deliverable —
components, orchestration model, control flow, key decisions — distinct from a target
repo's own `docs/architecture.md` that S3 creates/updates.
**Files/modules:** `docs/architecture.md`.
**Dependencies:** T8, ADR-001 (drafted in Step 2 after P0).
**DoD:** covers the component/module layout (architecture-proposal.md §3.1), the
engine/control-flow model (§3.2), and core abstractions (§3.3); references ADR-001 for
the decision record.

### T12.3 `docs/engineering-summary.md`
**Goal:** final engineering summary — plan/rationale, artifacts, risks/trade-offs/
validation, assumptions, limitations.
**Files/modules:** `docs/engineering-summary.md`.
**Dependencies:** T10.1–T10.3 (needs actual run outcomes, not just the plan, to
summarize).
**DoD:** the limitations section includes **all** of: (1) every item in
architecture-proposal.md §4.3's limitations list (the 1-of-8 policy, the G-9
re-planning extension, simple duration/call checks, central audit-repo publishing,
and workspace confinement's flags not being a hard boundary), and (2) every
SHOULD/COULD item listed in requirements.md §2's phase table that this slice didn't
build (central audit-repo publishing incl. re-publish/audit-repo-link-in-PR,
audit-record check in target CI, per-tool enforcement per agent role, resume after
process kill, `status` with merged detection, and every COULD item: project-level
hardening, stale-branch detection, automatic PR creation, central thresholds via
reusable CI workflow, central runner deployment, git-worktree isolation, OpenTelemetry
export) — each stated as built/not-built, not merely implied by omission. Also covers
assumptions (requirements.md §15 plus this proposal's "Assumed" O-items) and risks
(requirements.md §18), each tied to what was actually built or deferred.

---

**Total: 30 tasks across P0 + 12 blocks**, matching architecture-proposal.md §4.1's
effort estimates (~14.5h total effort, ~12.0h critical-path wall-clock, T12 overlapping
T10).
