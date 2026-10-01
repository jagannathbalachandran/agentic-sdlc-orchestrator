# Internals — Module and Class Reference

`README.md` and `docs/architecture.md` describe the system at the level a user or
a reviewer needs. This document goes one level deeper: every package, every
module, every class and function that matters, how they call each other, and a
real run traced through the code line by line. After reading this you should be
able to point at any behavior of the orchestrator and say which file produces
it, explain to someone else why it's built that way, and know exactly which
file(s) to open to change it.

Source of truth for *what* the system must do: `docs/requirements.md`. Source of
truth for *why* the major decisions were made: `docs/architecture-proposal.md`
and `docs/adr/ADR-001-orchestrator-architecture.md`. This document is the *how*
— the as-built map of `src/orchestrator/`.

---

## 1. Package map

```
src/orchestrator/
├── cli/            entry point + one module per command (register, run, approve, ...)
├── engine/         the FSM: stage graph, scheduler, retries, re-planning, locking
├── stages/         11 tiny StageSpec bindings — the declarative graph data
├── gates/          per-stage pass/fail checks (one class per gate)
├── policies/       whole-diff checks evaluated once at S6 (one class per policy)
├── executors/      the Executor protocol + real (claude -p) and mock implementations
├── profiles/       loads agents/profiles/*.toml and renders it into CLI flags
├── workspace/      git primitives + greenfield/clone workspace setup
├── audit/          everything written under runs/<project>/<run-id>/
├── config/         TOML config loading + schema + pre-run validation
├── models/         pydantic/dataclass shapes shared across all of the above
├── registry.py     project name -> repo location mapping (projects.json)
└── exceptions.py   every domain exception, in one place
```

**Dependency direction** (who is allowed to import whom — enforced by
convention, not a linter rule):

```
cli  ──depends on──►  engine  ──depends on──►  gates, policies, workspace, audit, models
                         │                            │
                         └──────────► executors, profiles, config, registry
```

`engine/` never imports from `cli/`. `gates/`, `policies/`, `executors/`,
`workspace/`, `audit/`, `config/`, `models/` never import from `engine/` or each
other except where noted below: `policies/base.py` imports `workspace/git_ops.py`
to build a diff; `engine/plan_tasks.py` **and** `audit/traceability.py` both
import parsing primitives from `gates/traceability_gate.py` — the two
deliberate exceptions, explained in §4.9/§4.10 and §7 (one shared parser for
`03-plan.md`'s task-line format, reused everywhere that file is read, instead
of three copies that can drift). This is what lets `CLAUDE.md`'s rule hold:
*"the core engine must not depend on how agents are executed."* `engine/`
only ever talks to an `Executor` through the one-method `Executor` Protocol
in `executors/base.py` — it has no idea whether a call goes to a real
subprocess or a JSON fixture on disk.

---

## 2. System flow diagram

```
                    ┌─────────────────────────────────────────────┐
                    │                   cli/main.py                │
                    │   parses argv, resolves ORCH_HOME, dispatches │
                    └───────────────────────┬───────────────────────┘
                                             │
             ┌───────────────┬──────────────┼──────────────┬───────────────┐
             ▼               ▼              ▼              ▼               ▼
       register.py      run.py        approve.py       reject.py      stop.py /
       validate.py      (start/      answer.py                        rollback.py
                         resume)
             │               │              │              │               │
             └───────────────┴──────┬───────┴──────────────┴───────────────┘
                                     ▼
                        engine/fsm.py  (the FSM / orchestration brain)
                     drive() · resolve_checkpoint() · stop_run() · rollback_to_checkpoint()
                                     │
            ┌────────────────────────┼─────────────────────────────┐
            ▼                        ▼                              ▼
   engine/locking.py        engine/graph.py (GRAPH)         engine/replanning.py
   one lock per project     stages/*.py → StageSpec         invalidate_from()
                             table, fixed at import time
                                     │
                                     ▼
                        engine/scheduler.py: run_batch()
                     (1 spec → run inline; 2+ ready siblings → threads)
                                     │
                                     ▼
                engine/runner.py: StageRunner.run()  /  fsm.py: _PerTaskS5aRunner.run()
                     entry gates → agent call → exit gates → commit → event
                     │                  │                        │        │
                     ▼                  ▼                        ▼        ▼
               gates/*.py      executors/{real,mock}.py   workspace/   audit/event_log.py
          (Gate.check())        Executor.execute()        git_ops.py   (hash-chained)
                                        │
                                        ▼
                               profiles/{loader,render}.py
                            agents/profiles/<role>.toml → prompt + flags
                                        │
                                        ▼
                                   claude -p  (real)   or   fixtures/mock/*.json (mock)

   at S6 only, after the stage itself passes:
                engine/fsm.py: _evaluate_s6_policies()
                     │
                     ▼
            policies/base.py: compute_diff()  ──►  policies/*.py (Policy.check())
            (git diff, base_commit..HEAD)          8 policies, each → PolicyResult

   on every terminal transition and at S8:
                audit/{metrics,report,pr_description,traceability}.py
                     read events.jsonl / graph_state → write metrics.json,
                     report.md, pr-description.md, traceability.md
```

Everything in the top half runs **once per stage, every stage**. Everything in
the bottom half (policies, final reports) runs **once per run**, at specific
points (S6, and run completion).

---

## 3. Models (`models/`) — the shared vocabulary

Every other package passes these shapes around; none of them contain behavior
beyond validation. All are pydantic `BaseModel`s (JSON-serializable, schema-
validated) except where noted as a plain `@dataclass` (in-process only, never
serialized).

| File | Class | What it is |
|---|---|---|
| `graph.py` | `StageId` (`StrEnum`) | The 11 fixed stage short codes: `S0`, `S1`, `S2`, `S3`, `S4`, `S5a`, `S5b`, `S6`, `S7a`, `S7b`, `S8`. |
| | `StageStatus` (`StrEnum`) | `pending / running / passed / failed / skipped / invalidated`. |
| | `CommitStrategy` (`StrEnum`) | `none / one / one_per_task` — how many commits a stage's runner makes. |
| | `StageSpec` | **The declarative definition of one stage**: `stage_id`, `owner_profile` (which `agents/profiles/*.toml` runs it, or `None`), `depends_on` (upstream `StageId`s), `allowed_write_paths` (globs, feeds `path_partitioning` policy), `commit_strategy`, `checkpoint_after` (an `ApprovalCheckpointKind` or `None`), `requires_agent` (`False` for S0/S6/S8 — orchestrator-only). One instance per stage lives in `stages/*.py`; `engine/graph.py` collects all 11 into `GRAPH`. |
| | `GateOutcome` | One gate's verdict: `gate_name`, `passed`, `details`. |
| | `StageResult` | One stage's row in `graph.json`: `status`, `attempts`, `started_at`/`finished_at`, `commits`, `gate_results`. |
| | `GraphState` | **The entire run's persisted state** — `graph.json` itself. Holds every `StageResult`, `pending_checkpoint`, `terminal_state`, `base_commit`, `agent_call_count`, `inject_fault`/`fault_injected`, `clarification_answer`, `design_rejection_feedback`, `retry_cycle_start_attempts` (per-stage, for item-1's fresh-retry-budget-per-replan fix), `executor_kind`, and everything else needed to resume a run from a cold process. This is the one object that round-trips through every CLI command. |
| `run.py` | `RunState` (`StrEnum`) | Run lifecycle: `created/preparing/running/awaiting_approval/completed/failed/rejected/stopped`. `TERMINAL_RUN_STATES` names the four that stop the loop. |
| | `ExecutorKind` (`StrEnum`) | `real` / `mock` — persisted on `GraphState` so a resumed run keeps using whichever executor it started with. |
| | `RunRecord` | The shape of `run.json`: identity, operator, timestamps, `effective_config_hash`, `scenario_hash`, `push_result`, etc. |
| `events.py` | `EventType` (`StrEnum`) | The 11 kinds of hash-chained event: `stage_started/stage_finished/gate_result/policy_result/approval_requested/approval_recorded/retry/rollback/stop/fault_injected/run_terminal`. |
| | `EventDraft` / `Event` | `EventDraft` is what a caller builds (no `sequence`/`hash` yet); `EventLog.append` turns it into an `Event` (adds `sequence`, `prev_hash`, `hash`). |
| `approvals.py` | `ApprovalCheckpointKind` (`StrEnum`) | `clarification/design/change_control/release` — the four checkpoint kinds. |
| | `ApprovalDecision` (`StrEnum`) | `approve/reject/reject_final/answer`. |
| | `ApprovalRecord` | One line of `approvals.jsonl`. |
| `decisions.py` | `Decision` | One line of `decisions.jsonl` — `decision_id`, `stage`, `actor`, `choice`, `rationale`. Written for a Clarification answer and for a Design rejection (both carry human reasoning that approvals.jsonl's fixed schema doesn't capture well). |
| `profile.py` | `AgentProfile` | One role's definition loaded from TOML: `persona`, `responsibilities`, `rules`, `enabled_tools`, `allowed_tool_patterns`, `output_contract`. |
| `agent_io.py` | `AgentCallOutcome` (`StrEnum`) | `success/timeout/invalid_output/error`. |
| | `AgentCallRequest` | What an `Executor.execute()` call needs: profile name, scenario/stage/attempt/task_id (mock fixture key), rendered prompt, workspace path, timeout, budget. |
| | `AgentCallResponse` | What a call returns: `outcome`, `summary`, `produced_ids`, `files_written`, `high_severity_findings` (S7b), `blocking_questions` (S1), `duration_seconds`, `cost_usd`, `session_id`, `raw_reply` (the agent's actual reply text — added after item 3/T9.9, see §8). **Deliberately not the deliverable content itself** — see §9's O-4 rationale. |
| | `AgentCallTranscript` | What's written to `agents/<agent_call_id>.json`: role, profile version hash, prompt, response — one file per real call. |
| `traceability.py` | `FunctionalRequirement`, `DesignDecision`, `Task`, `AcceptanceCriterion`, `CommitTrailers` | A richer, strongly-typed model of the FR→DD→Task→commit chain. **Not actually used by the real traceability pipeline** — `audit/traceability.py` and `gates/traceability_gate.py` both parse the chain straight out of markdown with regexes instead (see §10, "things that look wired but aren't"). Kept because it documents the intended shape and has its own unit test; a good candidate to either wire in for real or delete. |
| `_patterns.py` | (no class — regex constants) | `REQ_ID_PATTERN`, `FR_ID_PATTERN`, `AC_ID_PATTERN`, `DD_ID_PATTERN`, `TASK_ID_PATTERN`, `RUN_ID_PATTERN` — every ID format, defined once so every model that validates an ID string agrees on the shape. |

**Why pydantic everywhere:** every one of these gets written to disk as JSON and
read back by a *different process* (pause/resume, §7). pydantic gives schema
validation on read for free — a corrupted or hand-edited `graph.json` fails
loudly (`RunRecordError`) instead of the engine silently working from garbage.

---

## 4. Module-by-module reference

### 4.1 `config/` — layered TOML configuration

| File | What it does |
|---|---|
| `schema.py` | Pydantic models for the three config files: `DefaultsConfig` (`config/defaults.toml` — coverage threshold, `Limits`, `RetryLimits`, `PolicyConfig`), `ProjectConfig` (target's `.orchestrator/project.toml` — `project_name`, `approved_dependencies`), `ScenarioConfig` (target's `.orchestrator/scenarios/<id>.toml` — `scenario_id`, `req_id`, `requirement_text`, `base_ref`, `inject_fault`). |
| `loader.py` | `load_defaults_config` / `load_project_config` / `load_scenario_config` — read one TOML file with `tomllib`, validate against its schema, raise `ConfigValidationError` on either a missing file, malformed TOML, or a schema mismatch. |
| `validate.py` | `validate_run_prerequisites()` — the `orchestrator validate` command's entire logic: is the project registered (via an injected `ProjectLookup` callable, not a direct `registry.py` import — see §9 on dependency injection), do all three config files parse. Raises, returns nothing on success. |

### 4.2 `registry.py` — project name → repo location

One model (`ProjectRegistry`, a `dict[str, str]`), two functions
(`register_project`, `resolve_project`), backed by `ORCH_HOME/projects.json`
through `audit/run_record.py`'s atomic-write helpers (same file-safety primitive
every other on-disk record uses). `resolve_project` returns `None` for an
unknown project rather than raising — callers (`config/validate.py`,
`cli/commands/_common.py`) decide what that means.

### 4.3 `profiles/` — turning a TOML role definition into CLI inputs

| File | What it does |
|---|---|
| `loader.py` | `load_profile(path) -> LoadedProfile` — reads `agents/profiles/<role>.toml`, validates it as an `AgentProfile`, and returns it bundled with a `version_hash` (sha256 of the raw file bytes). The hash is what `C8-AC2` means by "profile version" — it's what gets recorded on every transcript, so a later change to a profile's wording is visible in the audit trail without needing git history. |
| `render.py` | Three pure functions that turn an `AgentProfile` into what `claude -p` actually needs: `render_system_prompt` (persona + responsibilities + numbered rules + output contract, joined into the `--append-system-prompt` text), `render_tools_flag` (`--tools` value, `None` if the profile needs nothing beyond `--restricted`'s own Write/Edit/Read defaults), `render_allowed_tools_flag` (`--allowedTools` value — the fine-grained auto-approval patterns, e.g. `Bash(python -m pytest *)`). |

### 4.4 `executors/` — the one seam between the engine and "how agents run"

| File | What it does |
|---|---|
| `base.py` | `Executor` — a one-method `Protocol`: `execute(request: AgentCallRequest) -> AgentCallResponse`. This single abstraction is what makes `engine/` testable without Claude and without the network (`CLAUDE.md`'s own rule). |
| `mock.py` | `MockExecutor` — looks up a JSON fixture for `(scenario_id, stage, attempt, task_id)`, trying `<stage>-<task_id>.json` (if a task ID is given), then `<stage>-<attempt>.json`, then bare `<stage>.json`, first under `fixtures/mock/<scenario_id>/`, then under `fixtures/mock/_generic/` if the scenario has nothing recorded. Materializes the fixture's `"files"` dict onto disk (so gates read real files, exactly like a real call would leave them) and returns an `AgentCallResponse` built from the fixture's `summary`/`produced_ids`/`files_written`/etc. No fixture found anywhere for a stage → synthesizes an `ERROR` outcome rather than crashing. |
| `real.py` | `RealExecutor` — builds the actual `claude -p ... --output-format json --restricted --add-dir <workspace> --allowedTools ... --permission-mode acceptEdits --append-system-prompt ... --max-budget-usd ...` command (`_build_command`), runs it as a subprocess with a per-call timeout that kills the *whole process tree* on expiry (`_kill_process_tree` — Windows: `taskkill /T /F`; POSIX: `os.killpg`), parses the JSON envelope `claude -p` prints (`_response_from_envelope`), and extracts the agent's own JSON summary from inside the envelope's `result` string — tolerantly: `_extract_last_json_object` scans backward for the last brace-balanced `{...}` block, so prose before/after the JSON doesn't break parsing (item 4/T9.9, after a real run proved the developer profile's "reply with ONLY JSON" instruction isn't a hard guarantee). Every failure path — timeout, non-JSON envelope, no JSON summary found — returns a real, non-empty `summary` naming what went wrong plus a reply snippet (item 3/T9.9), and `raw_reply` always carries the agent's actual text regardless of outcome, so a transcript is diagnosable even when parsing failed. |

**Why a Protocol, not an ABC:** `Executor`/`Gate`/`Policy` are all structural
(`typing.Protocol`) rather than inherited base classes. Nothing in `engine/`
ever does `isinstance` checks against them; any object with the right method
signature satisfies the contract, including test doubles that don't import the
protocol module at all. This is a deliberate, lightweight alternative to a
plugin-registration system (see §11 for what adding a new executor actually
involves).

### 4.5 `gates/` — per-stage pass/fail checks

| File | Class | Checks |
|---|---|---|
| `base.py` | `StageContext` (dataclass) | What every gate receives: `run_id`, `stage_id`, `attempt`, `workspace_path`. |
| | `Gate` (Protocol) | `check(context) -> GateOutcome`. |
| `schema_gate.py` | `SchemaGate` | **Stub, always passes.** Placeholder so every stage has at least one entry+exit gate recorded as an event; real per-stage output-schema validation (C5) was never built — the citation/stack/command gates below cover the same ground in practice (documented in `architecture-proposal.md` §4.3 item 7). |
| `existence_gate.py` | `ExistenceGate` | **Stub, always passes.** S2's exit gate ("every referenced file/symbol exists") — needs S2's real analysis output to check against, which the generic mock fixture doesn't provide. |
| `approval_gate.py` | `ApprovalGate` | Fails while `graph_state.pending_checkpoint` is set. **Built but not wired** — `drive()`'s own loop already refuses to start any stage while a checkpoint is pending, earlier and more directly than a per-stage gate could. Kept as an independently testable component matching the architecture's module list. |
| `traceability_gate.py` | `RequirementsCitationGate` (S1 exit) | Every `## FR-n[: title]` section in `01-requirements.md` must have a `Cites: REQ-n` line. Fails outright if it finds **zero** FR sections (not a vacuous pass) — this exact bug, on all three citation gates, is what item 2/T9.7 fixed after a real run's gate reported "0 DD(s) cite an FR" as a *pass*. |
| | `DesignCitationGate` (S3 exit) | Every `## DD-n[: title]` in `02-design.md` must cite ≥1 FR, **and** every FR in `01-requirements.md` must be cited by ≥1 DD (checked in both directions — a design that covers FR-1 four times while ignoring FR-2/FR-3 entirely used to pass). |
| | `PlanCitationGate` (S4 exit) | Every `## FR-n` section in `03-plan.md` has ≥1 task line citing a DD, **and** (added in item 2/T9.8) the shared `parse_plan_tasks()` function (below) must find at least one real task — a second, independent check using the exact parser S5a itself will use, so a plan that passes this gate is guaranteed parseable by S5a. |
| | `parse_plan_tasks(plan_md) -> tuple[(fr_id, task_id, dd_id, description), ...]` | **The single source of truth for 03-plan.md's task-line format.** Splits the file into `## FR-n` sections, then within each section finds every `- T-n.n (DD-n): <description>` line, capturing the description text from right after the `(DD-n):` prefix up to the *next* task line (or end of section) — not just the first line (item 1/T9.9: a real plan's multi-line task descriptions were silently truncated to one line before this fix). `engine/plan_tasks.py` wraps this function for S5a's own use (§4.9) — this is the one place `gates/` is imported *from* `engine/`, deliberately, so the two can never parse the same file two different ways again. |
| `technology_stack_gate.py` | `TechnologyStackGate` (S3 exit) | `02-design.md` must have a non-trivial `## Technology stack` section, and if the workspace has a real `pyproject.toml`, that section must actually mention Python. Added after item 6/T9.7: a real design named no language or framework at all. |
| `unchanged_on_retry_gate.py` | `UnchangedOnRetryGate` (S3 exit) | On any attempt after the first, `02-design.md` must differ from its content at the last commit — an agent that reports success but leaves the file byte-identical almost certainly didn't do the work. Added after item 4/T9.7: a Design-rejection retry passed every other gate while silently reproducing the original file. |
| `command_gate.py` | `TestCoverageGate` (S6 exit) | Runs the workspace's own `scripts/check.py` (using the workspace venv's python if one exists, else the orchestrator's own interpreter) and passes iff it exits 0. This is the **one** gate that satisfies "tests pass, coverage ≥ 85%, lint, types, dependency audit" all at once, by running the target's own combined gate script rather than five separate tool integrations (documented trade-off, `architecture-proposal.md` §4.3 item 7). A workspace with no `scripts/check.py` passes leniently rather than failing — a second, related documented limitation. |

### 4.6 `policies/` — whole-run-diff checks, evaluated once at S6

| File | What it does |
|---|---|
| `base.py` | `FileChange`/`WorkspaceDiff` (dataclasses) — one changed file's added/removed lines, and the whole diff bundle. `PolicyOutcome` (`StrEnum`: `ok/change_control/critical`). `PolicyResult` — one policy's verdict. `Policy` (Protocol) — `check(diff) -> PolicyResult`. `compute_diff(workspace_path, base_commit) -> WorkspaceDiff` — the one function that actually shells out to git (`git diff --name-only`, then `git diff -- <path>` per file), parsing unified-diff `+`/`-` lines into `FileChange`s. Every policy's `check()` is pure — it only ever reads a `WorkspaceDiff` object, never touches git or the filesystem itself. |
| `workspace_confinement.py` | `WorkspaceConfinementPolicy` — **critical**. Flags any changed path that's absolute or contains a `..` traversal segment. Defense in depth: a `git diff` inside the repo can't literally produce an escaping path, but the orchestrator must never *trust* that invariant without checking it directly (`CLAUDE.md`). |
| `path_partitioning.py` | `PathPartitioningPolicy` — **critical**. Every changed path must match *some* stage's `allowed_write_paths` glob (the union across all 11 `StageSpec`s — S6 can't attribute a file to the specific stage that wrote it, since siblings can share a commit). |
| `protected_paths.py` | `ProtectedPathsPolicy` — **critical**. Whole-file glob protection for `.github/**`, `scripts/check.py`, `.orchestrator/**`, every prior REQ's `00-source.md`, and secret-like filenames (`.env*` except `.env.example`); **section-aware** protection for specific `pyproject.toml` tables (`[tool.ruff]`, `[tool.mypy]`, `[tool.pytest.ini_options]`, `[tool.coverage.*]`, `[build-system]`) — diffed by content at base-commit vs HEAD, not by path, so a legitimate dependency-list edit in the same file doesn't trip it. |
| `main_protection.py` | `MainProtectionPolicy` — **critical**. Fails if `diff.current_branch == "main"` at all — every run should already be on its own `run/<run-id>` branch before any agent executes (D-5); being on `main` at S6 means that branching was somehow bypassed. |
| `secret_scan.py` | `SecretScanPolicy` — **critical**. Regex pattern scan (patterns from `config/defaults.toml`'s `policy.secret_scan_patterns`) over every added line. In-house patterns, not a dedicated scanner dependency — a documented, narrower-but-zero-new-dependencies trade-off. |
| `schema_change_control.py` | `SchemaChangeControlPolicy` — **change_control**. Flags any changed path matching a configured migration glob. |
| `diff_size_limit.py` | `DiffSizeLimitPolicy` — **change_control**. Flags the run's cumulative diff exceeding configured line or file-count limits (`config/defaults.toml`'s `limits.diff_size_limit_*`). |
| `dependency_control.py` | `DependencyControlPolicy` — **change_control**. Regex-scans added lines in `pyproject.toml`'s dependency tables for a package name not on the project's `approved_dependencies` list (`.orchestrator/project.toml`). |
| `registry.py` | `build_default_policies(approved_dependencies) -> tuple[Policy, ...]` — constructs the real 8, reading thresholds from `config/defaults.toml` and the allowed-path union from `engine/graph.GRAPH` directly. The one place all 8 are wired together; `cli/commands/_common.py:policies_for()` is the only caller. |

**Critical vs change_control**: a `CRITICAL` outcome from any policy stops the
run immediately (`terminal_state = STOPPED`) — these are containment
violations, not judgment calls. A `CHANGE_CONTROL` outcome pauses for a human
decision at the Change-control checkpoint — these are *legitimate but risky*
changes (a new dependency, a migration, a big diff) that a human should see
before they land, not things to block outright.

### 4.7 `workspace/` — git primitives and workspace setup

| File | What it does |
|---|---|
| `git_ops.py` | The lowest layer — every other module that touches git goes through this file, never `subprocess` directly. `run_git(cwd, *args) -> str` (stripped stdout, raises `GitCommandError` on non-zero exit) is the workhorse; `_run_git_content` is the one exception (unstripped, for `git show <commit>:<path>` where a trailing newline is meaningful — stripping it silently broke `UnchangedOnRetryGate`'s comparison until item 4/T9.7 found it). `commit_all`/`commit_paths` serialize through one process-wide `_COMMIT_LOCK` so S5a/S5b or S7a/S7b's concurrent threads never race `git add`+`git commit` on the same index; both fall back to returning current `HEAD` (not an empty commit) when a sibling branch already staged-and-committed everything first. Also: `init_repo`, `clone_repo`, `current_commit`/`current_commit_or_empty_tree` (the latter for diffing against a repo with zero commits yet), `read_file_at_commit`, `create_branch`/`current_branch`/`ensure_on_branch`, `rollback_to` (hard reset + clean, respecting `.gitignore` so the venv survives). |
| `manager.py` | Higher-level, greenfield/clone-specific setup: `init_greenfield_workspace` (copy the template, `git init`, one setup commit), `init_existing_workspace` (clone the target at `base_ref`), `create_run_branch`. **Mostly superseded** by `engine/fsm.py`'s own `_prepare_real_workspace`/`_s0_commit_hook`, which needed `00-source.md` to land in the *same* commit as the template copy/clone (this module's functions each make their own commit immediately, which would leave two). Still used directly by some tests; a real duplication worth resolving (§10). |

### 4.8 `engine/` — the orchestration brain

| File | What it does |
|---|---|
| `graph.py` | Imports all 11 `stages/*.py` modules and assembles `GRAPH: dict[StageId, StageSpec]` — the **one, fixed, whole-process-lifetime graph**. `get_stage_spec(stage_id)` is a thin lookup. |
| `scheduler.py` | `run_batch(specs, build_runner, build_request) -> tuple[BatchResult, ...]` — runs one spec inline, or N specs concurrently (one `ThreadPoolExecutor` worker each) when a batch has real siblings (S5a+S5b, S7a+S7b). `_run_one` is the one place a `StageGateFailure` exception gets caught and turned into a `FAILED` `StageRunResult` — everywhere else, a gate failure is a real exception. Concurrency safety lives entirely in the callees (`EventLog`'s internal lock, `git_ops`'s `_COMMIT_LOCK`) — this module just fans out and joins. |
| `locking.py` | One `<project>.lock` file (PID + timestamp + run_id) per project, so two processes can never drive the same project's run concurrently. `acquire_lock`/`release_lock`, with staleness reclaim: a lock is considered stale (and silently reclaimed) if its PID is dead (`pid_is_alive`, platform-specific: `ctypes`+`OpenProcess` on Windows, `os.kill(pid, 0)` on POSIX) or its age exceeds `max_run_duration_seconds`. Acquired at the top of `drive()`, released when `drive()` returns — never held across a process boundary. |
| `replanning.py` | `invalidate_from(graph_state, stage_id) -> tuple[StageId, ...]` — the entire mechanism behind "reject Design → re-run S3 onward" (C11). Computes every stage transitively downstream of `stage_id` (`_downstream_of`, a simple fixed-point walk over `GRAPH`'s `depends_on` edges), marks all of them `INVALIDATED` (resetting their attempt counts to 0 — they've never run in this branch of the re-plan), but keeps `stage_id`'s own attempt count (its re-run is a real next attempt, not a replay of attempt 1). Also records `retry_cycle_start_attempts[stage_id]` = the attempt count at invalidation time, so the bounded-retry check in `fsm.py` can count attempts *since this re-plan began* rather than the stage's whole-run total (item 1/T9.7's fix — without it, a rejection landing on a stage already near its retry ceiling had almost no real budget left for the re-plan). No bespoke "re-run" code path exists elsewhere — `drive()`'s normal batch-selection logic just re-selects anything that isn't `PASSED`/`SKIPPED`. |
| `plan_tasks.py` | Thin wrapper module: `PlanTask` (dataclass: `task_id`, `dd_id`, `fr_id`, `description`), `parse_plan_tasks(plan_md) -> tuple[PlanTask, ...]` (wraps `gates.traceability_gate.parse_plan_tasks`, converting its raw tuples into `PlanTask` objects), `parse_fr_to_req(requirements_md) -> dict[str, str]` (FR→REQ map, for S5a's commit trailers — reuses the same shared `FR_HEADING`/`_sections` primitives from `gates/traceability_gate.py`, for the same "never let two copies drift" reason). |
| `runner.py` | **`StageRunner`** — the standard per-stage lifecycle: entry gates → (if `requires_agent`) one executor call, with its transcript written if a `transcripts_dir` is configured → exit gates → commit hook → one `stage_finished` event. A gate failure records `stage_finished` (with `outcome: "gate_failure"`) before re-raising `StageGateFailure`, so a gate-failed stage is diagnosable from events alone (item 3/T9.7). `StageRunnerOptions` (frozen dataclass: `gates`, `commit_hook`, `profiles_root`, `transcripts_dir`, `artifacts_dir`) bundles the constructor's secondary parameters to stay under the project's 5-argument lint limit — the same "bundle into a dataclass" pattern recurs across this codebase (`CommitTrailerContext`, `_LoopResources`, `_ChainMaps`, ...). `StageGates` (entry/exit gate tuples), `StageRunRequest`/`StageRunResult` (what a run call takes/returns), `StageGateFailure` (the exception a failing gate raises), `CommitTrailerContext`/`commit_message_with_trailers` (builds the `Task:`/`FR:`/`Req:`/`Run:`/`Stage:` trailer block), `stage_commit_hook` (the default one-commit-per-stage hook; a no-op when `commit_strategy is NONE`). |
| `fsm.py` | **The largest module by far (~1,800 lines, ~60 functions/classes)** — described in full in §4.9. |

### 4.9 `engine/fsm.py` in detail — the FSM itself

This is where every other module gets wired together into an actual run. Four
functions are the **entire public surface** every CLI command calls:

| Function | Called by | What it does |
|---|---|---|
| `drive(request, executor, max_run_duration_seconds, policies=(), reliability=DEFAULT)` | `run.py`, `approve.py`, `reject.py`, `answer.py` | Loads (or creates) `GraphState`, acquires the project lock, then loops: pick the next ready batch (`_next_ready_batch` — every dependency `PASSED`/`SKIPPED`, nothing itself already `PASSED`), run it (`scheduler.run_batch`), record each result (`_record_batch_result` — the single biggest function, handling retries, checkpoints, S6 policy evaluation, run completion), check safe-stop limits, persist `graph_state` to disk, repeat — until a checkpoint is pending or the run reaches a terminal state. Releases the lock on the way out (`finally`). Returns a `DriveResult` (which stages ran, the final `GraphState`). |
| `resolve_checkpoint(ref, decision, comment, approver, max_run_duration_seconds)` | `approve.py`, `reject.py`, `answer.py` | Records an `ApprovalRecord`, clears `pending_checkpoint`, and — depending on `decision` — does one of: end the run as `rejected` (`REJECT_FINAL`); invalidate S3-onward and record the rejection comment on `graph_state.design_rejection_feedback` for the next `drive()` call's prompt to pick up (`REJECT` at the Design checkpoint — this exact wiring, previously missing, was item 5/T9.7's root-cause fix); invalidate S1-onward with the answer on `clarification_answer` (`ANSWER` at Clarification); or just clear the checkpoint so the next `drive()` continues (every other case, including a plain `APPROVE`). The caller (e.g. `approve.py`) always calls `drive()` again right after, in the same process, so approving genuinely continues the run rather than requiring a second CLI invocation. |
| `stop_run(ref, reason, max_run_duration_seconds)` | `stop.py` | Sets `terminal_state = STOPPED`, records a `stop` event, writes final metrics. Raises `RunAlreadyTerminalError` if the run already ended. |
| `rollback_to_checkpoint(ref, max_run_duration_seconds)` | `rollback.py` | `git_ops.rollback_to(workspace, graph_state.last_checkpoint_commit)` — hard-resets the workspace to the last commit made right after any stage passed. Raises `NoCheckpointRecordedError` if nothing has ever passed. |

**Everything else in the file is a private helper**, grouped by concern:

- **State I/O**: `run_dir`/`workspace_dir` (path conventions under `ORCH_HOME`), `generate_run_id` (`<scenario>-<YYYYMMDD>-<NNN>`, sequence-scanning existing run dirs), `_state_path`, `_load_or_init_graph_state`, `_load_existing_graph_state`, `load_graph_state` (public — used by `run.py --run-id` to resume).
- **Gate wiring**: `_gates_for(stage_id)` — the single function mapping each `StageId` to its real `StageGates(entry, exit)` tuple (every stage gets `SchemaGate`; S2 also gets `ExistenceGate`; S1/S3/S4 get their citation gate; S3 also gets `TechnologyStackGate`+`UnchangedOnRetryGate`; S6 gets `TestCoverageGate`).
- **Runner construction**: `_build_runner(resources, graph_state, spec)` — picks `_SkippedS2Runner` (greenfield, `base_ref is None`), `_PerTaskS5aRunner` (`commit_strategy is ONE_PER_TASK`), or plain `StageRunner`, wiring in `_gates_for`, `_commit_hook_for`, and the shared `profiles_root`/`transcripts_dir`/`artifacts_dir` via `StageRunnerOptions`. `_commit_hook_for` special-cases S0 (`_s0_commit_hook` — real workspace prep + `00-source.md`) and S8 (`_s8_commit_hook` — writes `report.md`/`pr-description.md` before Release approval); every other stage gets the generic `stage_commit_hook` from `runner.py`.
- **`_SkippedS2Runner(StageRunner)`**: overrides `run()` entirely — records `stage_started`/`stage_finished(status=skipped)` and returns immediately, no executor call, no gates.
- **Real workspace prep**: `_prepare_real_workspace` (template copy + `git init` for greenfield, or `clone_repo` for an existing target), `_create_workspace_venv` (`python -m venv` + `pip install -e ".[dev]"`, best-effort, only when the workspace has a `pyproject.toml`; resolves `workspace` to an absolute path first — item 2/T9.10's fix, after a relative `--orch-home` made the venv's own `ensurepip` bootstrap double-resolve its path and crash).
- **Prompt building**: `_STAGE_TASKS`-style per-stage instructions (what to read, what today's ask is, layered on top of the profile's own persona/rules), `_rendered_prompt_for` (adds `_technology_stack_instruction` for S3, and the rejection-feedback/clarification-answer text when present), `_task_prompt` (one S5a task's prompt).
- **`_PerTaskS5aRunner(StageRunner)`**: S5a's real per-task loop — `_plan_tasks` (via `engine/plan_tasks.py`), `_fr_to_req`, then for each task: skip it if `_already_committed_tasks` (sha lookup by the commit's own `Task:` trailer) says it's already landed (item 5/T9.9 — a retry resumes instead of redoing committed work); otherwise call the executor, write its transcript and artifacts, and `commit_paths` scoped to that task's `files_written`, with `commit_message_with_trailers`. Stops the loop (not the whole stage silently) on the first task that fails.
- **Replanning glue**: `_handle_stage_failure` (bounded-retry check using `retry_cycle_start_attempts`, records a `retry` event for an automatic retry — `_record_automatic_retry`, item 8/T9.7 — and, for S6 specifically, threads the real gate-failure output into an S5a fix-call subject via `_run_fix_call`), `_handle_s7b_findings` (high-severity findings → fix call → invalidate S6/S7a/S7b), `_fallback_to_human` (exhausted retries → `terminal_state = FAILED`), `_max_attempts_for` (which of the three `RetryLimits` applies to which stage).
- **Fault injection** (G-16): `_find_fault_mutation`/`_flip_return_true`/`_flip_return_false`/`_flip_equality` (small, deterministic, real-looking mutations to a file S5a just wrote under `src/`), `_inject_fault` (applies one, commits it, records a `fault_injected` event) — fires right after S5a passes, when the scenario's `inject_fault` flag is set and no mutation has been injected yet this run; S6's very next attempt then fails *for real*, and the normal S6-failure retry path (above) fixes it for real.
- **Policies at S6**: `_evaluate_s6_policies` — builds the diff (`policies.base.compute_diff`), runs every configured policy, records a `policy_result` event each, and reacts to the worst outcome: any `CRITICAL` → `STOP`; any `CHANGE_CONTROL` (and no critical) → pause at the Change-control checkpoint; otherwise let S6 finish normally.
- **Completion & reporting**: `_all_stages_passed`/`_complete_if_all_stages_passed`/`_complete_and_record`/`_finalize_completed_run` (the one place `terminal_state = COMPLETED` is ever set, from two call sites — a stage passing with no checkpoint attached, or a checkpoint being cleared), `_record_run_terminal` (emits the one `run_terminal` event every terminal state needs, since `metrics.json`'s `run_success` is computed from events alone), `_write_metrics_json`, `_commit_task_ids` (sha→task_id map from git trailers, used by `_write_traceability` so `traceability.md`'s commit column is actually populated — item 4/T9.10's fix for a bug that shipped the task-id-free version first), `_write_traceability`.
- **Safe-stop**: `_check_safe_stop_limits` — `agent_call_count > max_agent_calls` or run duration exceeded → `terminal_state = STOPPED`, a safety cap distinct from retry exhaustion, checked between batches (never mid-stage, so nothing is left half-committed).

### 4.10 `audit/` — everything under `runs/<project>/<run-id>/`

| File | What it does |
|---|---|
| `event_log.py` | `EventLog` — the hash-chained `events.jsonl` writer. `append(draft)` computes `sequence`/`prev_hash`/`hash` under an internal lock (the real serialization point for S5a/S5b or S7a/S7b writing from separate threads) and appends one JSON line. `verify()` recomputes the whole chain and returns `False` on any gap, reorder, or tampered field — the actual mechanism behind "tamper evidence" (D-7). `read_events(path)` is a free function (not a method) so metrics/report generation can read a log without ever constructing a writable `EventLog`. |
| `run_record.py` | `atomic_write_json(path, model)` / `read_json(path, model)` — every JSON file this project writes (`run.json`, `graph.json`, `projects.json`, lock files, `scenario.json`, `config.effective.json`) goes through these. Writes go to a temp file in the same directory, then `os.replace` — a reader can never observe a half-written file, even across a process crash mid-write. |
| `approvals_log.py` | `append_approval`/`read_approvals` — `approvals.jsonl`. |
| `decisions_log.py` | `append_decision`/`read_decisions`/`next_decision_id` (`<run_id>-decision-<NNN>`) — `decisions.jsonl`. |
| `agent_transcripts.py` | `write_transcript(directory, transcript)` — one `agents/<agent_call_id>.json` file per real agent call (role, profile version hash, prompt, full response including `raw_reply`). Added in item 3/T9.7 — before this, a failed call's full context was unrecoverable; a run record had zero transcripts. |
| `stage_artifacts.py` | `write_stage_artifacts(artifacts_dir, stage, workspace, files_written)` — copies each file a stage reported writing into `artifacts/<stage>/`, maintaining a `manifest.json` of content hashes, merged across calls (S5a's per-task loop calls this once per task, so a later task's files must not erase an earlier one's entries). |
| `metrics.py` | `compute_metrics(events) -> Metrics` — the whole of `metrics.json`, computed **from `events.jsonl` alone** (C13-AC1), never from `graph.json`. Pairs `stage_started`/`stage_finished` events into `_StageAttemptSpan`s, then derives: `run_success` (from the terminal `run_terminal`/`stop` event), `stage_first_pass_rate` (attempt-1 spans only; a `skipped` span is excluded entirely, neither counted as a pass nor a fail — item 8/T9.7's fix, after a skipped S2 was dragging this number down), `retry_count` (every `retry` event — both automatic bounded-retries and human-triggered re-plans count, by design: `rollback_count` already counts a purely human-invoked action the same way), `rollback_count`, `mttr_seconds` (mean, across stages that both failed and later recovered, of first-failure-to-first-success gap), `end_to_end_latency_seconds` (first to last event timestamp), `human_wait_seconds` (sum of every `approval_requested`→`approval_recorded` gap), latency with human wait subtracted out, and per-stage/per-agent-call latency breakdowns. |
| `report.py` | `generate_report(graph_state, metrics) -> str` — `report.md`: run identity, outcome, a per-stage status/attempts/commits table, the metrics table. Generated, never agent-written. |
| `pr_description.py` | `generate_pr_description(graph_state, run_record_location, audit_repo_url=None) -> str` — `pr-description.md`: run ID, record location, every commit sha (truncated), optionally a central-audit-repo link (the link itself is unbacked — no publisher exists, a documented SHOULD-not-built item). |
| `traceability.py` | `generate_traceability_report(inputs) -> str` / `backward_trace(inputs, commit_sha) -> BackwardTrace` — assembles the FR→AC→DD→Task→commit→test chain from `01-requirements.md`/`02-design.md`/`03-plan.md`/the real commit list/acceptance-test file contents, entirely by regex (shares `FR_HEADING`/`DD_HEADING`/`CITES_LINE`/`TASK_LINE_CAPTURING` with `gates/traceability_gate.py` — this module's own `AC_HEADING`/`TEST_TRACES_LINE` are its only unshared patterns). Renders `traceability.md` with an explicit `## Gaps` section listing any missing link (no AC, no DD, no task, no commit, no test) — generated, not agent-written, so "no gaps" is a real claim, not a self-report. `backward_trace` is the reverse direction: given a commit sha, walk its `Task:` trailer → the plan's FR nesting → the requirements' `Cites:` line, back to a REQ. **Not wired to a real graph stage** — requirements.md's own "Join S7" is a distinct row with no `StageId` of its own; S8 just depends on S7a+S7b directly. |

### 4.11 `cli/` — the only thing a human (or a grader) actually runs

| File | What it does |
|---|---|
| `main.py` | `build_parser()` (one `argparse` subparser per command module), `default_orch_home()` (`$ORCH_HOME` or `~/.orchestrator`), `main(argv)` — resolves `orch_home` to an **absolute** path (item 2/T9.10's fix — see §8) and dispatches to the matched command's `handle(args, orch_home)`. |
| `commands/_common.py` | Shared CLI-layer logic every command needs but `engine/fsm.py` deliberately stays independent of: `resolve_new_run_inputs`/`build_new_run_request` (registry + scenario-config resolution for a brand-new run), `executor_for(kind)`, `policies_for(target_repo_url)`, `build_reliability_limits()` (reads `config/defaults.toml` into a `ReliabilityLimits`), `record_run()` (writes `run.json` **and** `scenario.json`/`config.effective.json`, each hashed with the hash stored on `run.json` — item 7/T9.7), `push_if_completed()` (the one `git push` this project ever does, gated on `terminal_state is COMPLETED`), `describe()` (the one-line status string every command prints). |
| `register.py` | `orchestrator register <project> <repo-url>` → `registry.register_project`. |
| `validate.py` | `orchestrator validate <project> --defaults ... --project-config ... --scenario-config ...` → `config.validate.validate_run_prerequisites`. |
| `run.py` | `orchestrator run <project> <scenario> [--mock] [--operator NAME] [--run-id ID]` — the one command that can *start* a run (`generate_run_id` + `build_new_run_request`) or *resume* one (`--run-id` + `load_graph_state`, reusing whichever executor/target it started with). `--mock` still resolves a real registered target's scenario config when one exists, falling back to a bare stub request only when there's genuinely nothing to resolve (a CI/demo project with no real target). Calls `drive()`, then `push_if_completed`+`record_run`. |
| `approve.py` / `reject.py` / `answer.py` | Each calls `resolve_checkpoint()` with the matching `ApprovalDecision`, then `drive()` again (continuing the run in the same process), then `push_if_completed`+`record_run`. `reject.py` additionally supports `--final` (ends the run as `rejected`, no re-drive). |
| `stop.py` | `orchestrator stop <project> <run-id> [--reason TEXT]` → `stop_run()`. |
| `rollback.py` | `orchestrator rollback <project> <run-id>` → `rollback_to_checkpoint()`. |

### 4.12 `stages/` — the graph as data, not code

Eleven tiny files, each exporting exactly one `SPEC: StageSpec` constant (see
§3's `StageSpec` row for the field meanings; the full table is in
`requirements.md` §7). There is deliberately no behavior here — every stage
shares identical gate/policy/event-emission plumbing in `engine/runner.py`
and `engine/fsm.py`; a `stages/` file exists only to declare *which* profile
owns a stage, what it depends on, what it's allowed to write, how it commits,
and whether it pauses for approval. Adding a 12th stage means adding a 12th
file here plus wiring it into `engine/graph.py`'s `_STAGE_MODULES` tuple — see
§11.

---

## 5. One stage's full lifecycle — sequence diagram

This is what happens for **every** agent-backed stage (S1, S3, S4, S5b, S7a,
S7b — S5a is the per-task variant, shown separately below; S0/S6/S8 skip the
executor-call step entirely since `requires_agent=False`):

```
drive()                 scheduler       StageRunner          Executor        gates/*        audit/*
  │                      .run_batch()      .run()                                             events.jsonl
  │─ build_runner() ────────►│               │                                                   │
  │─ build_request() ───────►│               │                                                   │
  │                          │─ run() ──────►│                                                   │
  │                          │               │─ record STAGE_STARTED ─────────────────────────►│
  │                          │               │─ for gate in entry: gate.check(ctx) ────►│       │
  │                          │               │                                            │─────►│ (gate_result, each)
  │                          │               │     any gate failed? ──► raise StageGateFailure   │
  │                          │               │                                                   │
  │                          │               │─ executor.execute(request) ───────►│              │
  │                          │               │                                     │─ claude -p  │
  │                          │               │                                     │  or fixture │
  │                          │               │◄──────────── AgentCallResponse ────┘              │
  │                          │               │─ write_transcript() [if transcripts_dir] ───────►│ agents/<id>.json
  │                          │               │─ write_stage_artifacts() [if files_written] ────►│ artifacts/<stage>/
  │                          │               │─ for gate in exit: gate.check(ctx) ──────►│       │
  │                          │               │                                            │─────►│ (gate_result, each)
  │                          │               │     any gate failed? ──► raise StageGateFailure   │
  │                          │               │                                                   │
  │                          │               │─ commit_hook(ctx, spec) ──────────► workspace/git_ops.py
  │                          │               │                                     (commit_all / commit_paths)
  │                          │               │─ record STAGE_FINISHED (status, outcome, error) ─►│
  │                          │◄── StageRunResult ─┘                                               │
  │◄── BatchResult ──────────┘                                                                    │
  │─ _record_batch_result(): update graph_state.stages[id], handle retry/checkpoint/completion    │
  │─ atomic_write_json(graph.json) ──────────────────────────────────────────────────────────►│
```

A `StageGateFailure` from *either* gate pass is caught by
`scheduler._run_one`, turned into a `FAILED` `StageRunResult`, and handled by
`fsm._record_batch_result` exactly like an agent call that itself failed —
gates and agent failures feed the same bounded-retry path.

**S5a's per-task variant** replaces the single "executor.execute → gates →
commit" step with a loop: for each task in `03-plan.md` (parsed once via
`engine/plan_tasks.py`), skip it if already committed (git trailer lookup),
else call the executor with that task's own prompt, write its own transcript
and artifact entries, and `commit_paths` scoped to that task's files with its
own `Task:`/`FR:`/`Req:` trailers — one `STAGE_FINISHED` only at the very end
(success) or at the first task that fails.

---

## 6. End-to-end walkthrough: `greenfield-minimal`, mock executor

This traces a complete run, naming the exact function/class at each step. Same
scenario as `evidence/runs/README.md`'s human-approved runs, but using the mock
executor so it's reproducible without Claude.

### 6.1 `orchestrator register verify-greenfield <target-path>`

`cli/main.py:main()` parses argv → dispatches to `register.py:handle()` →
`registry.register_project(orch_home, "verify-greenfield", target_path)` →
reads `projects.json` (`registry._load_registry`, empty/new), adds the mapping,
`audit.run_record.atomic_write_json` writes it back.

### 6.2 `orchestrator run verify-greenfield greenfield-minimal --mock`

1. `main()` resolves `orch_home` to an absolute path, dispatches to
   `run.py:handle()`.
2. No `--run-id` given → `generate_run_id()` scans `ORCH_HOME/runs/verify-
   greenfield/` for existing `greenfield-minimal-20260930-*` dirs, returns the
   next sequence: `greenfield-minimal-20260930-001`.
3. `_build_new_mock_run_request()` tries `build_new_run_request()` first — this
   calls `_common.resolve_new_run_inputs()`, which looks up the project in the
   registry (`registry.resolve_project`), reads
   `<target>/.orchestrator/scenarios/greenfield-minimal.toml` via
   `config.loader.load_scenario_config` (`req_id=REQ-2`, the shorten+redirect
   requirement text, `base_ref=None` → greenfield). Builds a `DriveRequest`
   carrying all of it plus `executor_kind=MOCK`.
4. `fsm.drive(request, executor=MockExecutor(fixtures/mock), ...)` is called.
   - `engine.locking.acquire_lock()` takes the `verify-greenfield.lock`.
   - `_load_or_init_graph_state()` finds no existing `graph.json` → creates a
     fresh `GraphState(run_id=..., scenario_id=..., req_id="REQ-2", ...)`.
   - Loop, iteration 1: `_next_ready_batch(graph_state)` — every `StageSpec`
     in `GRAPH` with all `depends_on` satisfied and not yet `PASSED`. First
     call: only `S0` qualifies (no dependencies). `scheduler.run_batch((S0
     spec,), ...)` — one spec, runs inline (no thread pool).
     - `fsm._build_runner()` sees `S0`'s `requires_agent=False` → plain
       `StageRunner`, with `_s0_commit_hook` as its commit hook.
     - `StageRunner.run()`: entry `SchemaGate` passes trivially; since
       `requires_agent=False`, no executor call — `response =
       NO_AGENT_RESPONSE`; exit `SchemaGate` passes; commit hook fires:
       `_s0_commit_hook` calls `_prepare_real_workspace` (greenfield →
       `shutil.copytree(templates/python-service, workspace)` +
       `workspace.git_ops.init_repo` + `git remote add origin <target>`),
       `ensure_on_branch("run/greenfield-minimal-20260930-001")`,
       `_create_workspace_venv` (template has a `pyproject.toml` → real venv +
       `pip install -e ".[dev]"`), writes `00-source.md` with the frozen
       requirement text, commits everything as `"S0: workspace prepared"`
       with `Run:`/`Stage:` trailers.
     - `STAGE_STARTED`/`STAGE_FINISHED` events append to
       `runs/.../events.jsonl` via the shared `EventLog`.
   - `_record_batch_result()`: `graph_state.stages[S0] = StageResult(status=
     PASSED, attempts=1, commits=(sha,))`; `base_commit` captured now (S0 just
     finished, its real content is the diff base every S6 policy check will
     use). `graph_state` persisted (`atomic_write_json(graph.json)`).
   - Iteration 2: `S1` now ready. `_build_runner` → plain `StageRunner`,
     `owner_profile="analyst"`, `_gates_for(S1)` → entry `SchemaGate`, exit
     `(SchemaGate, RequirementsCitationGate)`. `StageRunner.run()` calls
     `MockExecutor.execute()` → looks up
     `fixtures/mock/greenfield-minimal/S1-1.json` — no such directory exists
     in this repo, so it falls straight through to
     `fixtures/mock/_generic/S1.json`, same as every scenario with no
     dedicated fixtures (a real registered scenario only needs mock fixtures
     if it's ever driven with `--mock`; the real `greenfield-minimal` runs in
     `evidence/runs/` all used the real executor, so no fixture directory
     for it was ever needed) — materializes `01-requirements.md` onto disk,
     returns a `SUCCESS`
     `AgentCallResponse`. `RequirementsCitationGate` reads the file back,
     confirms every `## FR-n` cites a `REQ-n`. Commit:
     `"S1: stage complete"`.
   - Iteration 3: `S2`. `graph_state.base_ref is None` (greenfield) →
     `_build_runner` returns `_SkippedS2Runner` → records
     `stage_finished(status=skipped, reason=...)`, no executor call, no gate.
     `graph_state.stages[S2] = StageResult(status=SKIPPED)`.
   - Iteration 4: `S3`. `owner_profile="architect"`. `_rendered_prompt_for`
     appends `_technology_stack_instruction` (reads the workspace's own
     `pyproject.toml`, tells the architect to use that stack). Exit gates:
     `RequirementsCitationGate`'s S3 sibling `DesignCitationGate`,
     `TechnologyStackGate`, `UnchangedOnRetryGate` (attempt 1 → trivially
     passes, nothing to compare against yet). `S3.checkpoint_after =
     ApprovalCheckpointKind.DESIGN` — once S3 passes,
     `_record_batch_result` sees `spec.checkpoint_after is not None`, sets
     `graph_state.pending_checkpoint = DESIGN`, records an
     `approval_requested` event.
   - `drive()`'s loop condition (`terminal_state is None and
     pending_checkpoint is None`) is now false → loop exits. Lock released.
     `GraphState` persisted with `pending_checkpoint = "design"`.
5. Back in `run.py:handle()`: `push_if_completed()` is a no-op (not
   `COMPLETED`); `record_run()` writes `run.json` (`state=awaiting_approval`)
   plus `scenario.json`/`config.effective.json`, each hashed. Prints `run
   greenfield-minimal-20260930-001: awaiting_approval (design)` and
   `run-id=greenfield-minimal-20260930-001`.

### 6.3 `orchestrator reject verify-greenfield greenfield-minimal-20260930-001 --comment "name a tech stack" --approver alice`

1. `reject.py:handle()` → `fsm.resolve_checkpoint(ref, REJECT, comment,
   "alice", ...)`.
2. Appends an `ApprovalRecord` (`approvals.jsonl`). `decision is REJECT and
   checkpoint is DESIGN` → sets `graph_state.design_rejection_feedback =
   comment`, calls `engine.replanning.invalidate_from(graph_state, S3)`:
   walks `GRAPH` to find everything downstream of S3 (S4, S5a, S5b, S6, S7a,
   S7b, S8), marks them all `INVALIDATED` (attempts reset to 0), keeps S3's
   own attempt count, records `retry_cycle_start_attempts[S3] = 1`. Also
   appends a `Decision` to `decisions.jsonl` (choice=`"reject"`,
   rationale=the comment) and a `retry` event (`trigger: design_rejection`).
   `pending_checkpoint` cleared.
3. `reject.py` calls `drive()` again, same process. `_next_ready_batch` now
   sees `S3` (`INVALIDATED` counts as "not yet passed", and its one
   dependency `S2` is `SKIPPED`, which `_is_satisfied` treats as done) →
   re-runs it. `_rendered_prompt_for` this time appends: *"This design was
   REJECTED by a human reviewer with this feedback — revise 02-design.md to
   address it: name a tech stack"* — reading straight from
   `design_rejection_feedback`. The bare `_generic/S3.json` fixture would
   return the *same* content on attempt 2 as attempt 1 — for a real retry
   test you'd add a `fixtures/mock/<scenario>/S3-2.json` (attempt-specific)
   with genuinely revised content, exactly as
   `fixtures/mock/e2e-full-run/S3-2.json` does for the project's own E2E CLI
   test. `UnchangedOnRetryGate` (attempt 2 now) compares the new
   `02-design.md` against `read_file_at_commit(HEAD, "02-design.md")` — if
   they're still identical, the gate fails right here with a clear reason,
   rather than passing silently (the exact bug item 4/T9.7 found and this
   gate exists to catch). With a revised `S3-2.json` in place, S3 passes
   again → `checkpoint_after=DESIGN` fires again → pauses at Design a second
   time.

### 6.4 `orchestrator approve ... --comment "looks good" --approver alice` (Design), then again at Release

First `approve`: `resolve_checkpoint(APPROVE, ...)` just clears the
checkpoint (no special-case branch matches a plain approve) and records the
`ApprovalRecord`; `drive()` continues from S4. S4 (`planner`) produces
`03-plan.md`; its exit gate is `PlanCitationGate`, which both checks every FR
section has a citing task line **and** calls the shared
`gates.traceability_gate.parse_plan_tasks()` to confirm it finds ≥1 real task.

S5a and S5b become ready together (`_next_ready_batch` returns both specs in
one batch) → `scheduler.run_batch` spins up a `ThreadPoolExecutor` with 2
workers. On the S5a thread, `_build_runner` returns `_PerTaskS5aRunner`
(`commit_strategy is ONE_PER_TASK`): `_plan_tasks()` parses every task out of
`03-plan.md`. The bare `_generic/S4.json` fixture only ever defines one task
(`T-1.1`), so illustrating the actual loop needs a scenario with a real
multi-task plan — either a dedicated fixture set (`fixtures/mock/per-task-
demo/` ships exactly this, with `T-1.1`/`T-1.2` under `FR-1`) or a real
`claude -p` call, which is what every real run in `evidence/runs/` produced.
With two tasks: `_already_committed_tasks()` finds nothing yet; for `T-1.1`
the runner calls the executor, writes `agents/S5a-1-T-1.1.json`,
`commit_paths` with `Task: T-1.1`/`FR: FR-1`/`Req: REQ-2` trailers; same for
`T-1.2`. On the S5b thread (running concurrently), the test engineer writes
acceptance tests from the design's acceptance criteria, one commit. Both
threads' `commit_all`/`commit_paths` calls serialize through
`git_ops._COMMIT_LOCK`; both threads' `EventLog.append` calls serialize
through `EventLog`'s own internal lock — neither stage waits on the other's
*agent call*, only on the shared git index and event file for the brief
moment of committing/logging.

Once both finish, S6 becomes ready (`depends_on=(S5A, S5B)`, both must be
`PASSED`). `requires_agent=False` → `TestCoverageGate` runs the workspace's
own `scripts/check.py`. Say it fails once (a real lint issue) — `_record_
batch_result` sees `status is FAILED`, calls `_handle_stage_failure`:
`attempts_this_cycle (1) < s6_failure_max_attempts` → `_record_automatic_
retry` appends a `retry` event (`trigger: automatic_retry`), and because
`stage_id is S6_VERIFY`, `_run_fix_call` makes one more developer call
(`subject = "S5a-fix: address S6 verification failure\n\n" +
<the real check.py failure output>`), committed as `S5a-fix: address S6
verification failure`. S6 re-runs (attempt 2), this time passes.

S7a and S7b run as the next parallel pair (same mechanics as S5a/S5b, minus
the per-task split). S8 (`requires_agent=False`) is the Release join:
`_s8_commit_hook` generates `report.md`/`pr-description.md` from the current
`GraphState`+computed `Metrics` *before* committing, so they're ready to read
when the checkpoint fires — `checkpoint_after=RELEASE` pauses the loop.

Second `approve` (Release): `resolve_checkpoint` clears the checkpoint;
`_complete_if_all_stages_passed` (called from inside `_record_batch_result`
on *this* resolve, since there's no further stage to run) finds every
`StageSpec` in `GRAPH` satisfied → `terminal_state = COMPLETED`,
`_record_run_terminal` appends the `run_terminal` event, `_finalize_
completed_run` writes final `metrics.json` and `traceability.md`
(`_commit_task_ids` reads every commit's `Task:` trailer so the traceability
table's commit column is populated correctly). Back in `approve.py`:
`push_if_completed` now actually runs `git push origin run/greenfield-
minimal-20260930-001` (since `terminal_state is COMPLETED`); `record_run`
writes the final `run.json`.

### 6.5 What's on disk afterward

`ORCH_HOME/runs/verify-greenfield/greenfield-minimal-20260930-001/` holds
`run.json`, `scenario.json`, `config.effective.json`, `graph.json`,
`events.jsonl` (every event from §6.2–6.4, hash-chained),
`approvals.jsonl`, `decisions.jsonl`, `agents/` (one JSON per real call),
`artifacts/<stage>/` (content-hashed copies), `metrics.json`, `report.md`,
`pr-description.md`. `ORCH_HOME/workspaces/verify-greenfield/.../` holds the
actual git repo: every commit from S0 through S8, on `run/greenfield-minimal-
20260930-001`, each with `Run:`/`Stage:` trailers and, for task commits,
`Task:`/`FR:`/`Req:` too — plus `traceability.md`, generated after the fact
and (by design) never itself committed.

---

## 7. Why it's designed this way

This section ties specific design choices back to the modules above; the full
reasoning for each lives in `docs/architecture-proposal.md`'s O-1..O-10 and
`docs/adr/ADR-001-orchestrator-architecture.md`.

- **Stateless pause/resume, not a long-running process.** `GraphState` is the
  *entire* mutable state of a run, and it's reloaded from `graph.json` at the
  top of every single `drive()`/`resolve_checkpoint()` call. There is no
  in-memory singleton, no daemon, no socket. This is why `approve` can run in
  a completely different OS process than `run` did — proven directly by
  `tests/integration/test_pause_resume.py`. The cost is that every mutation
  must go through `GraphState` and get persisted before the process can exit;
  the benefit is that a crashed process loses at most the work since the last
  `atomic_write_json`, never the whole run.
- **`StageSpec` is declarative data, not a class hierarchy.** Adding a stage
  never means subclassing anything — it means writing one `StageSpec(...)`
  constant. All *behavior* (gates, commit strategy, prompt building) is kept
  in `engine/fsm.py`'s own dispatch functions (`_gates_for`,
  `_commit_hook_for`, `_rendered_prompt_for`), keyed off `StageId`/
  `commit_strategy`/`requires_agent`. This trades a small amount of
  indirection (you look in two places, not one, to understand a stage) for
  every stage sharing identical plumbing with zero duplication.
  `_PerTaskS5aRunner` is the one deliberate exception — S5a's commit-per-task
  behavior genuinely doesn't fit the generic one-call-one-commit shape, so it
  gets its own `StageRunner` subclass rather than contorting the generic path.
- **Protocols (`Executor`, `Gate`, `Policy`), not base classes.** None of
  these need shared implementation, only a shared method signature — a
  `Protocol` lets a test fixture or a fixture-driven stub satisfy the
  contract without importing anything from the real module at all, which is
  exactly what keeps `engine/` genuinely decoupled from `executors/` (and
  from the mock vs. real distinction specifically).
- **One lock for commits, one lock for events — both inside the modules that
  own the resource, not in the scheduler.** `scheduler.run_batch` has *no*
  locking code of its own; it just starts threads. `git_ops._COMMIT_LOCK` and
  `EventLog`'s internal `threading.Lock` are what actually make S5a/S5b (or
  S7a/S7b) safe to run concurrently. This keeps the concurrency-safety
  reasoning local to the one place each shared resource is touched, instead
  of scattered across every caller.
- **Flat JSON/JSONL files, not a database.** Every run record is independently
  readable with `cat`/`Get-Content`/`jq` — no query layer, no schema
  migration story, no server to run. The trade-off (explicit in
  `architecture-proposal.md`) is no cross-run aggregation and no concurrent-
  writer story beyond the two in-process locks above; see §11 for what
  swapping this out would actually involve.
- **Gates read files; policies read diffs; neither trusts the agent's own
  report.** `AgentCallResponse.summary` is a *hint* for a human (and for
  deciding `invalid_output` vs `success`) — every gate and every policy
  re-reads the actual file or the actual `git diff`, never the response
  object's claims. This is `CLAUDE.md`'s "never trust an agent's own
  assessment" made structural, not just a stated rule.
- **Shared parsing primitives, learned the hard way.** `gates/
  traceability_gate.py`'s `FR_HEADING`/`_sections`/`parse_plan_tasks` are
  imported by both `engine/plan_tasks.py` and `audit/traceability.py` — the
  *only* place `gates/` is imported from outside itself. This exists because
  three independent copies of "parse a `## FR-n` heading" drifted out of sync
  with each other across T9.7–T9.9 (one fixed to accept a real agent's
  titled heading, two others not), and each drift produced a real run
  failure that passed every mock-based test. The fix wasn't "write a better
  regex" three times — it was "there must be exactly one regex." Any future
  file-format convention this project parses in more than one place should
  follow the same pattern from the start.

---

## 8. What real runs found that mock-based tests didn't

Full detail and root-cause writeups: `docs/build-notes.md` (search `T9.7`
through `T9.10`) and `evidence/runs/README.md`. The pattern, once, because it's
the single most important lesson this codebase's own history demonstrates:

> **Every mock-based test passed; every human-approved real run failed —
> because parsing or gate logic had been tested against fixture content
> written by the same person who wrote the parser, not against what a real
> agent actually writes** (titles after heading IDs, task descriptions that
> wrap across lines, prose around a JSON summary, non-ASCII punctuation).

Concretely, in the order they were found and fixed (all in `engine/fsm.py`,
`gates/traceability_gate.py`, `executors/real.py`, or `workspace/git_ops.py`
unless noted):

1. A Design rejection's re-run got an identical prompt (feedback was never
   persisted anywhere the prompt builder could read it) — fixed by
   `GraphState.design_rejection_feedback`.
2. Citation gates matched only a bare `## DD-1` heading, never `## DD-1:
   <title>` — passed vacuously ("0 DD(s) cite an FR" reported as a pass).
3. No agent transcripts existed at all — a failed call was undiagnosable
   without re-running it.
4. A retry that left `02-design.md` byte-identical passed every other gate
   silently.
5. `03-plan.md`'s task parser had drifted between `gates/
   traceability_gate.py` (fixed to accept titled headings) and its own
   separate copy in `engine/plan_tasks.py` (not yet fixed) — S4's gate passed
   a plan that S5a then found "no parseable tasks" in.
6. The same parser kept only a task's *first line* — a real plan's multi-line
   task descriptions were silently truncated before reaching the developer's
   prompt.
7. `AgentCallResponse.summary` was `""` on every `invalid_output` — no
   `raw_reply` field existed, so the actual agent text was unrecoverable.
8. A relative `--orch-home` made a subprocess's own command argument
   double-resolve against its own `cwd`, crashing `python -m venv`'s
   `ensurepip` bootstrap.
9. Three `subprocess.run(..., text=True)` call sites had no explicit
   `encoding`, so Windows decoded real agent content (an em dash, a smart
   quote) with the console's codepage instead of UTF-8, crashing a reader
   thread.
10. `traceability.md`'s commit column was built with `task_id` always `None`
    — every FR showed "no commit" despite real, correctly-trailered commits
    existing.

Each of these got a regression test using the *exact* real content that
exposed it, not a synthetic minimal case — see `tests/unit/engine/
test_plan_tasks.py`'s `REAL_PLAN_MD` for the clearest example.

---

## 9. Design injection and testability — the dependency-injection pattern

A few modules deliberately take an abstraction instead of reaching for the
concrete implementation directly, specifically so they can be tested without
the real thing:

- `config/validate.py`'s `validate_run_prerequisites` takes a
  `ProjectLookup = Callable[[str], str | None]` rather than importing
  `registry.resolve_project` directly — tests pass a stub dict-backed
  lookup; `cli/main.py` partial-applies the real, registry-backed one.
- `engine/fsm.py`'s `drive()` takes an `Executor` (never constructs one
  itself) and a `policies: tuple[Policy, ...]` (defaults to empty — only the
  CLI layer, via `policies_for()`, ever supplies the real 8).
- `engine/scheduler.py`'s `run_batch` takes `build_runner`/`build_request`
  as callables, not concrete objects — `fsm.py` is what actually knows how
  to build a real `StageRunner` or `_PerTaskS5aRunner`; the scheduler only
  knows "given a spec, get something runnable."

This is why the whole engine can be driven end-to-end in a unit test (see
`tests/unit/engine/test_fsm.py`'s `test_end_to_end_real_graph_reaches_
completed_through_all_nine_stages`) with zero network access and zero real
subprocesses, in under a second.

---

## 10. Things that look wired but aren't (and known duplication)

Worth knowing before you go looking for where something is "actually used":

- **`gates/approval_gate.py`'s `ApprovalGate`** is fully implemented and
  tested, but nothing ever constructs one in the real pipeline — `drive()`'s
  own loop-condition check (`pending_checkpoint is None`) already does the
  same job, earlier. Either delete it or genuinely wire it as a defense-in-
  depth entry gate.
- **`models/traceability.py`'s rich pydantic models**
  (`FunctionalRequirement`, `DesignDecision`, `Task`, `CommitTrailers`) are
  used only by their own unit test. The real traceability pipeline
  (`audit/traceability.py`, `gates/traceability_gate.py`) parses markdown
  with regexes directly and never instantiates these. Either wire them in as
  the actual intermediate representation, or remove them.
- **`workspace/manager.py`'s `init_greenfield_workspace`/
  `init_existing_workspace`** are superseded by `engine/fsm.py`'s own
  `_prepare_real_workspace` (needed to land `00-source.md` in the same
  commit as the template copy/clone, which `manager.py`'s functions — each
  making their own immediate commit — can't do). `manager.py` is still
  imported directly by some tests. A real, if minor, duplication.
- **`gates/schema_gate.py`/`gates/existence_gate.py`** are permanent stubs
  (always pass) standing in for output-schema validation that was never
  built — not forgotten, documented in `architecture-proposal.md` §4.3 item
  7, but worth knowing they currently add an event, not a real check.
- **The parser-drift history (§7's last bullet, §8 items 5–6)** is the
  strongest argument in this codebase for "if two modules need to understand
  the same file format, there must be exactly one function that understands
  it" — not a one-off fix, a pattern to keep applying.

---

## 11. How to change or extend this

**Add a 12th stage.** Write `stages/sNN_name.py` exporting one `SPEC =
StageSpec(...)` (pick `depends_on`, `allowed_write_paths`,
`commit_strategy`, `checkpoint_after` if it should pause). Add the module to
`engine/graph.py`'s `_STAGE_MODULES` tuple. If it needs a real agent call, add
an `agents/profiles/<role>.toml` and reference it as `owner_profile`; add a
per-stage prompt instruction in `engine/fsm.py`'s prompt-building section. If
it needs non-default gates, add a branch in `_gates_for`. If it needs a
non-generic commit hook, add a branch in `_commit_hook_for`. Add a generic
mock fixture at `fixtures/mock/_generic/<StageId>.json` so every scenario-
specific test that doesn't care about this stage still passes.

**Add a gate.** New file in `gates/`, implement `check(context:
StageContext) -> GateOutcome` (a `@dataclass` with a `gate_name` field is the
existing convention — see any gate above). Wire it into `_gates_for` for the
stage(s) it applies to. If it reads the same file format another gate already
parses, **reuse that parser** (§7's lesson) rather than writing a second
regex.

**Add a policy.** New file in `policies/`, implement `check(diff:
WorkspaceDiff) -> PolicyResult` (decide its `PolicyOutcome`: `CRITICAL` stops
the run, `CHANGE_CONTROL` pauses for a human). Add it to
`policies/registry.py:build_default_policies`'s returned tuple. If it needs
config, add a field to `config/schema.py`'s `PolicyConfig` and a default in
`config/defaults.toml`.

**Add an agent role.** Write `agents/profiles/<role>.toml`
(`name`/`persona`/`responsibilities`/`output_contract`, optionally
`rules`/`enabled_tools`/`allowed_tool_patterns`) — `profiles/loader.py`
validates it against `models/profile.py:AgentProfile` automatically, nothing
else to register. Assign it to a stage's `owner_profile`.

**Change retry/timeout/budget behavior.** All of it is config-driven from
`config/defaults.toml` (`Limits`, `RetryLimits` in `config/schema.py`) —
no code change needed to tune numbers. To change the *policy* (e.g. a 4th
kind of bounded retry, not just S6-failure/invalid-output/S7b-findings), add
a field to `RetryLimits` and a branch in `engine/fsm.py:_max_attempts_for`.

**Add a CLI command.** New file in `cli/commands/`, with `COMMAND_NAME`,
`add_subparser(subparsers)`, `handle(args, orch_home) -> int`. Register it in
`cli/main.py`'s `build_parser()` loop and `_handlers()` dict. Reuse
`cli/commands/_common.py`'s helpers rather than re-deriving
registry/policy/executor resolution.

**Swap the executor** (e.g. a different CLI agent, or a hosted API instead of
a subprocess). Implement the one-method `Executor` protocol
(`execute(request) -> AgentCallResponse`); nothing in `engine/` needs to
change — `cli/commands/_common.py:executor_for()` is the only place that
picks a concrete class.

**Move off flat files to a database.** The seam is `audit/run_record.py`'s
`atomic_write_json`/`read_json` and the `*_log.py` append/read pairs — every
caller already goes through these, never raw file I/O. Swapping the
implementation behind that same signature (writing rows instead of files) is
the whole migration; `engine/`, `gates/`, `policies/` never touch a file path
directly for run-record data.

**Split `engine/fsm.py`.** It's the one module that's outgrown a single file
(~1,800 lines). A natural split along its own section comments (§4.9 above):
prompt-building, per-task S5a runner, retry/replanning glue, fault injection,
policy evaluation, and completion/reporting could each become their own
module under `engine/`, with `fsm.py` left holding just the four public
entry points and the batch loop. No behavior change needed — purely a
file-organization refactor, and the biggest single thing that would make this
codebase easier to onboard onto.
