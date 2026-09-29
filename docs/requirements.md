# Requirements — Agentic SDLC Orchestrator

Status markers:
- **[DECIDED]** — settled; the architecture must treat it as a constraint.
- **[OPEN]** — for the architecture proposal: options, trade-offs, recommendation.
- Priority: **MUST** (Phase 1 — built first) · **SHOULD** (Phase 2 — if time allows) · **COULD** (documented as next step).

---

## 1. What we are building

An **orchestrator**: a command-line system that takes a software requirement for a
target project and drives it through the full SDLC — requirements, codebase analysis,
design/architecture, planning, implementation, testing, verification, documentation,
review and release readiness — using AI agents, under explicit governance.

- The orchestrator is the **machine**; it does not contain the product it builds.
- The **target project** lives in its own git repo. Agents work on a disposable clone
  of it (the *workspace*), always on a run branch.
- Agents execute work **inside stages**. The orchestrator controls everything
  **between stages**: order, gates, policies, approvals, retries, rollback, audit.
- Principle: *agents execute under defined autonomy boundaries; humans own oversight,
  approvals and final quality.* Operationally: **agents propose, humans approve and merge.**

### End to end
1. The project team adds a scenario (and its approved-dependency list) under `.orchestrator/` in **their own product repo** — they never modify the orchestrator.
2. The engineer runs `orchestrator run <project> <scenario>` on their machine.
3. The orchestrator prepares an isolated workspace and a run branch.
4. Agents execute the stage graph; gates check every stage; policies are enforced on every
   change; the run pauses for human approval at defined checkpoints.
5. On failure: retry with feedback, roll back, fall back to the human, or safely stop.
6. Everything is recorded (events, decisions, approvals, agent transcripts, metrics, report)
   and traceable from requirement to commit.
7. After release approval, the run branch is pushed. The engineer raises the PR; the
   approver reviews and merges. The target's CI enforces the gates again at merge time.

---

## 2. Build scope for this submission [DECIDED]

The document describes the **full design**. The build is phased; **Phase 1 is built first
and must be complete and working before anything in Phase 2 starts.**

| Phase | Scope |
|---|---|
| **Phase 1 — MUST** | Every capability item marked MUST in §10: stage graph with conditional S2 and parallel joins; gates incl. tests + coverage ≥ 85%; core policies; four approval checkpoints with pause/resume via commands; bounded retries, rollback, fallback to human, safe-stop; rejection-driven re-planning; requirement-folder traceability + per-task commits with trailers; decision lineage; hash-chained event log, report, PR description, metrics; **automatic publishing of run records to the central audit repo (§11.1)**; real + mock executors; agent profiles; push after release approval; the three scenarios run and recorded |
| **Phase 2 — SHOULD** | Automatic re-publish of records that failed to publish; audit-record check in the target's CI; per-tool enforcement per agent role; resume after process kill mid-stage; `status` with merged detection |
| **COULD (documented only)** | **Project-level hardening** of global rules (extra gates, protected paths, approvals, higher thresholds, tighter limits — §9); stale-branch detection; automatic PR creation; central thresholds via a reusable CI workflow; central runner deployment; git-worktree isolation for parallel stages; OpenTelemetry export |

Anything not built is listed in the final engineering summary as a limitation, with the design already described here.

---

## 3. Glossary

| Term | Meaning |
|---|---|
| **Project** | A target system, identified by its **repo name** (e.g. `url-shortener-ai-assisted`). |
| **Scenario** | A reusable input for a project: requirement ID, requirement text, base ref, settings. |
| **Requirement (REQ)** | The original request, with a stable ID (e.g. `REQ-003`) assigned in the scenario. Never edited after S0. |
| **FR / AC** | Functional requirement / acceptance criterion derived in S1 (e.g. `FR-8`, `FR-8.AC2`). |
| **Design decision (DD)** | A decision made in S3 (e.g. `DD-2`), each linked to the FRs it serves. |
| **Task** | A unit of implementation work from S4 (e.g. `T-8.2`), grouped under its FR. |
| **Run** | One execution of a scenario, with a unique ID and a complete run record. |
| **Stage** | One SDLC step in the graph, executed by an agent or the orchestrator. |
| **Gate** | Check at a stage boundary: **entry** (may it start?) and **exit** (is the output acceptable?). |
| **Policy** | A governance rule enforced by the orchestrator; agents cannot bypass it. |
| **Approval checkpoint** | A pause until a human decides: approve, reject with feedback, or answer questions. |
| **Workspace** | Disposable clone of the target for one run; the only place agents may write. |
| **Run record** | Orchestrator-owned evidence for one run; agents never write to it. |
| **Agent profile** | Role definition: persona, responsibilities, allowed tools, output contract. |
| **Executor** | How an agent runs: **real** (`claude -p`) or **mock** (recorded responses). |
| **Template** | Approved scaffold used to start greenfield workspaces. |

---

## 4. Roles and ownership

| Role | Owns / does |
|---|---|
| **Platform team** | **Owns and maintains the orchestrator**: its code, the global stage graph, gates, policies, approvals, templates and agent profiles. Changes reviewed via PR with CODEOWNERS. Project teams cannot change any of it. |
| **Project team** | **Uses** the orchestrator; does **not** own or modify it. Owns only its product repo, including `.orchestrator/` (scenarios + approved-dependency list). (Hardening global rules per project: COULD, §9.) |
| **Engineer / operator** | Runs the orchestrator, raises PRs. Does not modify the orchestrator. |
| **Approver** | Answers clarifications, approves/rejects checkpoints, reviews and merges PRs (same person in the prototype; separate role in records). |
| **Agents** | Execute one stage within their profile. No authority beyond it. |
| **Orchestrator** | The only component that commits, changes stage state, writes run records, or pushes. |

---

## 5. Deployment and trust model [DECIDED]

### 5.1 Where it runs
- **Prototype: local CLI on the engineer's machine.** Prerequisites: orchestrator installed
  (released package; a clone for the prototype, used unmodified), Claude Code installed and
  authenticated, git access to the target repo. The engineer never edits orchestrator code.
- **Production path (COULD): central runner.** The same core runs on platform infrastructure
  (service or CI runner); engineers submit scenarios and give approvals; records are central
  by default. The core is kept independent of where it runs.

### 5.2 What each control protects against

| Threat | Control | Where enforced |
|---|---|---|
| Agent oversteps (writes outside workspace, touches protected files, weakens gates, adds deps) | Policies, protected paths, orchestrator-enforced thresholds, least-privilege profiles | Orchestrator (local) |
| Agent manipulated by content in the repo (prompt injection) | Enforcement lives outside agents; repo content treated as data | Orchestrator (local) |
| Honest mistakes in project config/scenarios | Schema validation before the run | Orchestrator (local) |
| Operator modifies the orchestrator or global rules locally | **Merge-time enforcement**: target CI re-runs the gates on GitHub; branch protection blocks merge on failure. **Tamper evidence**: orchestrator version + effective-config hash recorded and shown in the PR | GitHub (cannot be bypassed locally) + audit record |
| Run records lost, edited or never looked at | Hash-chained event log; **automatic publishing to the central audit repo**; audit link in every PR (all MUST) | Orchestrator + central audit repo |

**Principle:** local runs give fast, governed feedback; **the merge gate enforces**. Nothing
reaches `main` without passing CI on GitHub, regardless of what happened locally.

---

## 6. Lifecycles (fixed for all projects)

### 6.1 Project lifecycle [DECIDED]
1. **Prepare the target repo**: add `.orchestrator/project.*` (approved-dependency list) and
   `.orchestrator/scenarios/<scenario>.*` via a normal PR to `main`. For greenfield,
   create an empty GitHub repo and commit only `.orchestrator/` first.
2. **Register** locally: `orchestrator register <repo-url>` (maps project name → repo URL).
3. **Run** any number of times per scenario.
4. **Track** delivery: `orchestrator runs list <project>` (MUST) / `status` (SHOULD).

**Config source:** project config and scenarios are read from the target repo's **`main` at
run start** (governed by PR review), while the workspace code starts from the scenario's
**base ref** (which may be a tag without `.orchestrator/`). Both commit IDs are recorded.

### 6.2 Run lifecycle [DECIDED]
```
created → preparing → running ⇄ awaiting_approval
                         │
                         ├─→ completed (release approved) → pushed
                         ├─→ failed
                         ├─→ rejected
                         └─→ stopped
```

| Terminal state | Meaning | Triggered by |
|---|---|---|
| **completed** | Release approved; branch pushed | Release approval |
| **failed** | The **work** could not be made acceptable | Retries + fallback exhausted and the human ends the run; baseline gates fail on existing code (S0); unrecoverable setup error |
| **rejected** | Human rejected at a checkpoint without re-planning | `reject --final` |
| **stopped** | Halted for **safety or control**, regardless of the work | `orchestrator stop`; max run duration or max agent calls reached; **critical policy violation** (write outside workspace, secret in a change, attempt to write/push `main`, edit of `00-source.md` or `.orchestrator/`) |

Both `failed` and `stopped` leave the branch at the last good commit, record the reason and release the project lock.

### 6.3 Branching, pull request and merge policy [DECIDED]
- All agent work happens on **`run/<run-id>`**, created from the base ref. Nothing is ever committed to `main`.
- **Only the orchestrator commits and pushes**; it pushes only the run branch, only after Release approval.
- **The engineer raises the PR** into `main`, using the generated `pr-description.md`
  (summary, requirement → FR → task coverage, approvals, gate results, orchestrator version,
  config hash, link to the run record).
- **The approver reviews and merges.** The orchestrator never merges.
- **Latest-`main` compatibility** is ensured in GitHub: PR CI tests the **merge result** with
  current `main`; branch protection requires the CI check and "branches up to date before
  merging". *(Branch protection on private repos may depend on the GitHub plan; the setting
  is documented either way.)*
- The greenfield template ships this CI workflow.

### 6.4 Delivery lifecycle
```
pushed → merged      (branch head is an ancestor of origin/main)     — SHOULD
pushed → abandoned   (human marks it, with reason)                   — SHOULD
pushed → stale       (main moved since the run's base commit)        — COULD
```

---

## 7. Standard stage graph [DECIDED — structure; OPEN — engine]

Defined **once, globally**, in the orchestrator (platform-owned). In Phase 1 every project runs exactly this graph with these gates and approvals; per-project hardening is COULD (§9).

```
S0 Prepare
   │
S1 Requirements ──(blocking questions?)──► [Clarification] ─► S1 re-run with answers
   │
S2 Codebase analysis        (every existing codebase; skipped for greenfield)
   │
S3 Design & architecture ──► [Design approval]
   │
S4 Plan
   │
   ├──► S5a Implement + unit tests (task by task) ──┐
   └──► S5b Acceptance / integration tests ─────────┤  parallel, join
                                                    ▼
S6 Verify
   ├─ gates fail ──► back to S5a with the failure output (max 3) ──► exhausted: rollback + pause for human
   └─ risky change (migration / new dependency / protected path / large diff) ──► [Change-control approval]
   │
   ├──► S7a Docs (documentation paths only) ─┐
   └──► S7b Review ──────────────────────────┤  parallel, join
                                             ▼
        high-severity finding ──► back to S5a with findings (max 2) ──► S6 again; exhausted: pause for human
   │
S8 Release readiness ──► [Release approval] ──► push run branch
```

| Stage | By | Output (→ where) | Commits | Entry gate | Exit gate |
|---|---|---|---|---|---|
| **S0 Prepare** | Orchestrator | Workspace, run branch, venv; `00-source.md` (→ workspace); baseline results (→ record) | 1 (setup) | Config valid; project lock; target reachable | Workspace ready; baseline gates pass (non-greenfield) |
| **S1 Requirements** | Analyst | `01-requirements.md`: FRs with ACs, assumptions, open questions | 1 | S0 passed | Schema valid; every FR has ≥1 AC; every FR cites the REQ; IDs continue existing numbering; no unanswered blocking questions |
| **S2 Codebase analysis** | Analyst | Impact analysis: modules, APIs, data model, migrations, risks (→ record) | 0 | S1 passed; not greenfield | Schema valid; every referenced file/symbol exists |
| **S3 Design & architecture** | Architect | `02-design.md` (DD-n, each → FRs; contracts: endpoints, schemas, signatures); `docs/architecture.md` created (greenfield) or updated if significant (§7.1) | 1 | S1 (+S2) passed | Every FR covered by ≥1 DD; contracts defined; significance decision recorded; **Design approval** |
| **S4 Plan** | Planner | `03-plan.md`: tasks under each FR (one FR → many tasks), dependencies, each task → DD(s) and expected files | 1 | Design approved | No cycles; every FR has ≥1 task; every task → ≥1 FR; planned paths allowed |
| **S5a Implement + unit tests** | Developer, **one call per task** in plan order | Code + unit tests in `src/`, `tests/unit/` | **1 per task** | S4 passed | Each task's files within allowed paths |
| **S5b Acceptance tests** | Test engineer | Tests in `tests/acceptance/`, each tagged with its `FR-n.ACm`; built from ACs + contracts, not the implementation | 1 | S4 passed | Every AC has ≥1 test |
| **Join S5** | Orchestrator | — | — | — | Both branches finished |
| **S6 Verify** | Orchestrator | Gate + policy results (→ record) | 0 | Join done | **All tests pass; coverage ≥ 85%** (§7.4); lint, types, security, dependency audit; all policies; change-control approval if triggered |
| **S7a Docs** | Technical writer | README / API docs (**documentation paths only**) | 1 | S6 passed | Docs updated for every changed API; no non-doc paths touched |
| **S7b Review** | Reviewer | Findings with severity (→ record) | 0 | S6 passed | No open high-severity findings |
| **Join S7** | Orchestrator | `traceability.md` generated (→ workspace) | 1 | Both finished | Traceability complete (§7.2) |
| **S8 Release readiness** | Orchestrator + human | Checklist, `report.md`, `pr-description.md` (→ record) | 0 | Join done | Checklist complete; **Release approval** → push |

### 7.1 Architecturally significant change [DECIDED]
`docs/architecture.md` must be updated when the change adds a component or service, a data
store or table, an external dependency or integration, changes a public API contract, or
changes a cross-cutting concern (security, persistence, error handling). The architect
records the yes/no decision and reason in the lineage either way.

### 7.2 Traceability [DECIDED]

**The chain (every link is written down, in both directions):**
```
Scenario (REQ-003, orchestrator input)
  → Baselined requirement   00-source.md      verbatim, frozen at S0, hash recorded
    → Functional requirements 01-requirements.md  FR-8, FR-9 … each with ACs, each cites REQ-003
      → Design decisions       02-design.md        DD-1, DD-2 … each lists the FRs it serves
        → Tasks                03-plan.md          grouped under each FR: FR-8 → T-8.1, T-8.2 …
                                                   each task lists its DD(s) and expected files
          → Commits            one per task (S5a), with git trailers: Task, FR, Req, Run, Stage
          → Tests              acceptance tests tagged FR-n.ACm (S5b); unit tests per task (S5a)
  → traceability.md            the whole chain as one table, incl. commit IDs; generated at Join S7
```

**Two baselines are recorded**, so every change is measured against a fixed starting point:
- **Requirement baseline** — `00-source.md`: the original requirement exactly as given.
  Written by the orchestrator at S0, protected (agents cannot edit it), hash recorded.
  All later documents interpret it; none replace it.
- **Code baseline** — the exact commit the run started from (`base ref` → commit ID),
  recorded in `run.json` and at the top of `traceability.md`.

**In the target repo, one folder per requirement:**
```
docs/requirements/REQ-003-click-analytics/
├── 00-source.md        # baselined requirement (frozen)
├── 01-requirements.md  # FRs + ACs, each citing REQ-003
├── 02-design.md        # DDs, each citing its FRs; contracts
├── 03-plan.md          # tasks under each FR, each citing its DDs
└── traceability.md     # full chain with commit IDs and tests (generated)
```

**`traceability.md` (generated at Join S7) — example:**
```
Requirement: REQ-003 (00-source.md, sha256 9f2c…)   Code baseline: a1b2c3d (tag baseline-greenfield)
Run: brownfield-analytics-20260929-001

| FR   | AC       | Design | Task  | Commit  | Tests                                   |
|------|----------|--------|-------|---------|-----------------------------------------|
| FR-8 | FR-8.AC1 | DD-1   | T-8.1 | 4e5f6a7 | tests/acceptance/test_fr8.py::test_ac1  |
| FR-8 | FR-8.AC2 | DD-2   | T-8.2 | 8b9c0d1 | tests/acceptance/test_fr8.py::test_ac2  |
| FR-9 | FR-9.AC1 | DD-3   | T-9.1 | 2e3f4a5 | tests/acceptance/test_fr9.py::test_ac1  |
```

**Every orchestrator commit carries git trailers:**
```
T-8.2: record click event on redirect

Run: brownfield-analytics-20260929-001
Stage: S5a
Task: T-8.2
FR: FR-8
Req: REQ-003
```
Non-task commits (S0, S1, S3, S4, S5b, S7a, Join S7) carry `Run`, `Stage` and `Req`
(and `FR` where applicable).

**So you can go either way:**
- **Forward** (requirement → code): REQ → FRs → DDs → tasks → commits and tests, via the
  documents and `traceability.md`.
- **Backward** (code → requirement): any line → `git blame` → commit → trailers → task → FR → REQ.

For existing codebases, new FR IDs continue the existing numbering (the URL shortener has
FR-1…FR-7, so new ones start at FR-8). The traceability folder is part of the pushed branch
and is merged with the code, so it stays in the product repo permanently.

### 7.3 Parallel stages writing to one workspace [DECIDED]
Parallel agents are separated by **path partitioning**, enforced by policy:
S5a → `src/`, `tests/unit/`; S5b → `tests/acceptance/` (own `conftest.py`);
S7a → documentation paths only; S7b → read-only. Git-worktree isolation with a merge at
the join is the cleaner alternative (COULD).

### 7.4 Test and coverage gate [DECIDED]
- S6 requires **all tests pass** and **coverage ≥ 85%**, plus lint, types, security, audit.
- The orchestrator passes the threshold itself (explicit `--cov-fail-under`), never trusting
  the target's config — agents could lower `fail_under`. Gate config files are protected paths.
- Threshold is global in Phase 1. Per-project raising (never lowering) is COULD (§9).

### 7.5 Why implementation and tests are split this way [DECIDED]
S5a writes code **and unit tests** (they need internal details). S5b writes **acceptance
tests** from ACs and S3's contracts, independently — so they check what the code *should*
do. Contract mismatches surface at S6 and are fixed by the bounded S5a loop.

---

## 8. Repository and runtime layout [DECIDED]

**Orchestrator repo (platform-owned):**
```
agentic-sdlc-orchestrator/
├── src/orchestrator/          # engine, gates, policies, executors, CLI (layout: OPEN)
├── config/defaults.*          # global stage graph, gates, policies, approvals, limits, threshold
├── templates/python-service/  # greenfield scaffold incl. CI workflow and .orchestrator/ example
├── agents/profiles/           # one profile per agent role
├── fixtures/mock/             # recorded agent responses (mock executor)
├── evidence/runs/             # the three showcase run records, committed
├── tests/                     # orchestrator tests (mock executor only)
├── scripts/check.py
├── docs/                      # assignment, requirements, ADRs, tasks, transcripts
├── CLAUDE.md
└── AI_LOG.md
```

**Target repo (project-owned):**
```
<target-repo>/
├── .orchestrator/
│   ├── project.*              # approved-dependency list (hardening fields: COULD)
│   └── scenarios/*.*          # REQ ID, requirement text, base ref, settings
├── docs/requirements/REQ-…/   # traceability folders (written by runs, merged via PR)
└── … product code …
```

**Runtime home on the engineer's machine** (`ORCH_HOME`, default `~/.orchestrator/`):
```
~/.orchestrator/
├── projects.*                 # registry: project name → repo URL
├── workspaces/<project>/<run-id>/   # target clone + its venv; agents' only writable area
└── runs/<project>/
    ├── index.jsonl            # one line per run
    └── <run-id>/              # run record (§11)
```

| Path | Purpose | Used when |
|---|---|---|
| `config/defaults.*` | Global graph, gates, policies, mandatory approvals, limits, coverage threshold | Every run; base layer |
| `templates/python-service/` | Approved foundation for greenfield | S0 of greenfield runs |
| `agents/profiles/` | Role definitions | Every agent call; version hash recorded |
| `.orchestrator/project.*` (target) | Approved-dependency list for the dependency policy | Every run of that project; read from `main` |
| `.orchestrator/scenarios/*` (target) | Requirement inputs | Selected at run start; snapshotted |
| `fixtures/mock/` | Recorded agent outputs | Tests, CI, reviewer demo |
| `ORCH_HOME/workspaces/…` | Disposable per-run workspace | S0–S8 |
| `ORCH_HOME/runs/…` | Run records | During and after runs |
| `evidence/runs/` | Curated showcase runs | Submission / interview |

---

## 9. Configuration layering [DECIDED]

**Phase 1 (MUST):** the global configuration (platform-owned) defines the stage graph, gates,
policies, approvals, limits and coverage threshold for **every** project. A project supplies
only its **inputs**: scenarios and the approved-dependency list. Both are schema-validated by
`orchestrator validate` before a run.

**Project hardening (COULD):** a later layer **global → project → scenario** where a project may
**tighten, never loosen** the global rules (extra gates, protected paths or approvals, a higher
coverage threshold, lower limits). Any attempt to loosen would fail validation. Designed now,
not built.

`.orchestrator/` and `00-source.md` are protected paths during runs.

---

## 10. Capabilities and acceptance criteria

### C1. CLI — MUST
`register`, `validate`, `run [--mock]`, `approve`, `reject [--final]`, `answer`, `stop`, `runs list`, `runs show`.
(`resume` after crash, `status`, `abandon` — SHOULD.)
- AC1 `validate` reports schema errors in project config and scenarios before any run.
- AC2 `run` creates run ID, record and workspace, then starts S0.
- AC3 `--mock` runs the full graph with recorded responses, no Claude, no network.
- AC4 `runs show` prints stages, status, approvals, key metrics.

### C2. Projects and scenarios — MUST
- AC1 Project config and scenarios are read from the target's `main` at run start; commit recorded.
- AC2 Each scenario has a unique REQ ID; the scenario snapshot + hash are stored in the record.
- AC3 A run cannot start for an unregistered project or an invalid config.

### C3. Workspace — MUST
- AC1 Workspace at `ORCH_HOME/workspaces/<project>/<run-id>/`.
- AC2 Greenfield: template copied, `git init`, setup commit. Existing: clone at base ref; base commit recorded.
- AC3 Run branch created before any agent executes; target deps installed in the workspace venv only.
- AC4 Non-greenfield: baseline gates run first; failure ends the run as `failed`.
- AC5 `00-source.md` written at S0 with its hash recorded.

### C4. Stage graph — MUST
- AC1 No stage starts before all dependencies pass.
- AC2 S5a/S5b and S7a/S7b run in parallel; joins wait for both; one failure fails the join.
- AC3 S2 skipped with reason for greenfield; always runs otherwise.
- AC4 Graph validation rejects cycles and unknown stages.

### C5. Gates — MUST
Types: output schema, command gates (tests, coverage, lint, types, audit), existence check (S2), traceability checks (S1/S3/S4/S5b/Join S7), policy checks, approvals.
- AC1 Every stage's entry and exit gates come from the global config.
- AC2 A failed exit gate never lets downstream stages start.
- AC3 Every gate result is recorded as an event.
- AC4 Code gates use real checks, never agent self-assessment.
- AC5 S6 fails if any test fails or coverage < threshold, enforced by the orchestrator.

### C6. Policies — MUST (global list below) · COULD (project hardening)
- **Workspace confinement** — post-stage check: no changes outside the workspace.
- **Path partitioning** — each stage writes only its allowed paths (§7.3).
- **Protected paths** — `.github/`, `scripts/check.py`, quality config, `.orchestrator/`, `00-source.md`, secrets files.
- **Dependency control** — new deps only from the project's approved list; else change-control approval.
- **Schema change control** — new/changed migrations → change-control approval.
- **Secret scan** — pattern scan of every stage diff; a hit is critical → `stopped`.
- **Diff size limit** — above threshold → change-control approval.
- **Main protection** — no commit/push to `main`; attempt is critical → `stopped`.
- AC1 Each policy has a test proving detection and the specified outcome.
- AC2 Violations recorded with policy ID, evidence (file/line) and outcome.
- AC3 (COULD) With project hardening, a project config that loosens a global policy fails validation.

### C7. Approval checkpoints — MUST
Clarification (conditional), Design (always), Change control (conditional), Release (always).
- AC1 The run pauses with state persisted; `approve`/`reject`/`answer` in a later command resumes it.
- AC2 Reject requires feedback; feedback triggers re-planning unless `--final`.
- AC3 Each record: checkpoint, artifact hashes shown, decision, comment, approver, time.
- AC4 Mandatory checkpoints cannot be removed by config.

### C8. Agent profiles and executors — MUST (profiles, executors) · SHOULD (per-tool enforcement)
Profiles for analyst, architect, planner, developer, test engineer, technical writer, reviewer:
persona, responsibilities and limits, allowed tools (least privilege), inputs, output contract, rules.
- AC1 Engine code depends only on the executor interface.
- AC2 Each call uses one profile; profile version hash recorded.
- AC3 Invalid output → same-stage retry with validation errors (max 2).
- AC4 Every call records role, profile version, prompt, response, duration, outcome.
- AC5 Repo content passed as data; policies enforced outside agents.
- AC6 (SHOULD) A role cannot use tools outside its profile.

### C9. Reliability controls — MUST (resume after kill: SHOULD)
- Bounded retries: invalid output 2; S6 failures 3; S7b high findings 2 — each with feedback.
- Fallback: exhausted retries → pause for the human with full context (intervene, re-plan, or end as `failed`).
- Rollback: reset to the last good commit.
- Safe-stop: `stop` command, max duration, max agent calls, critical violation.
- AC1 Retry limits never exceeded (tested).
- AC2 After rollback, the workspace equals the last good commit.
- AC3 Safe-stop leaves no partial commit; `stopped` recorded with trigger.
- AC4 (SHOULD) After a process kill, `resume` continues from the last completed stage.

### C10. Traceability and decision lineage — MUST
- Requirement folder (§7.2); per-task commits with trailers; decisions with depends-on links.
- AC1 Every FR cites the REQ; every DD cites ≥1 FR; every task cites ≥1 DD and sits under ≥1 FR (checked by gates).
- AC2 Every S5a commit carries Task, FR, Req, Run and Stage trailers; every task has ≥1 commit.
- AC3 `traceability.md` lists every FR → AC → DD → task → commit → test, with no gaps; generated, not agent-written.
- AC4 `00-source.md` hash at the end equals the hash recorded at S0; code baseline commit recorded.
- AC5 Backward trace works: from any changed line, `git blame` + trailers reach the task, FR and REQ.
- AC6 Each decision records ID, stage, actor, choice, rationale, depends-on (decision IDs + artifact hashes).

### C11. Re-planning — MUST (rejection-driven) · SHOULD (other triggers)
- AC1 Rejecting the design with feedback re-runs S3 with the feedback, then S4 onwards; S1/S2 kept.
- AC2 Downstream stages are marked `invalidated`; events record the trigger.
- AC3 Re-planned output passes the same gates and approvals.

### C12. Observability and audit — MUST
- Append-only, **hash-chained** `events.jsonl` with correlation IDs (run, stage, attempt, agent call).
- `run.json` records orchestrator version and **effective-config hash**; both appear in `pr-description.md`.
- Live terminal progress; `report.md`; `pr-description.md`.
- AC1 Every transition, gate, policy result, approval, retry, rollback, stop is an event.
- AC2 Editing or deleting an event is detected by chain verification.
- AC3 No secrets written to any record (redaction tested).
- AC4 Run records are published automatically to the central audit repo (§11.1) at every approval pause and at the end of every run, whatever the outcome.
- AC5 `pr-description.md` contains the link to the run's folder in the audit repo.

### C13. Metrics — MUST
Run success rate; stage first-pass rate; retry and rollback frequency; MTTR (failure → next
success of that stage); end-to-end latency with and without human wait; stage and agent-call latency.
- AC1 `metrics.json` per run, computed from events only.

### C14. Delivery — MUST (push) · SHOULD (merged/abandoned) · COULD (stale)
- AC1 Push only after Release approval; target URL and branch recorded.
- AC2 (SHOULD) Merge status derived from git.

### C15. Orchestrator quality — MUST
- Ruff (incl. security), mypy strict, pytest ≥ 85% coverage, pip-audit, CI.
- AC1 Tests run entirely on the mock executor.
- AC2 Unit tests for engine, gates, policies, re-planning, metrics; one end-to-end mock run per scenario.

---

## 11. Run record [DECIDED]

`ORCH_HOME/runs/<project>/<run-id>/`, written only by the orchestrator:

| File | Contents |
|---|---|
| `run.json` | IDs (run, project, scenario, REQ), operator, times, outcome + reason; target URL, config commit (main), base ref + base commit, run branch, push result; orchestrator version, template version, profile versions, executor + model, effective-config hash |
| `scenario.*` | Snapshot of the scenario |
| `config.effective.*` | Merged configuration used |
| `graph.json` | Per stage: status, attempts, times, commits, gate results |
| `artifacts/<stage>/` | Stage outputs with content hashes |
| `decisions.jsonl` | Decision lineage |
| `approvals.jsonl` | Approval records |
| `events.jsonl` | Hash-chained audit log |
| `agents/` | Prompt + response per agent call |
| `metrics.json` | Metrics |
| `report.md` | Human-readable summary |
| `pr-description.md` | Ready-to-paste PR description |

**Run ID:** `<scenario>-<YYYYMMDD>-<seq>`; also the run-branch suffix.

| Question | Where |
|---|---|
| What happened? | `report.md` |
| Which runs exist? | `runs/<project>/index.jsonl`, `runs list` |
| Which requirement/FR/task led to this code? | commit trailers; `docs/requirements/REQ-…/traceability.md` |
| What did I approve, when, on what? | `approvals.jsonl` |
| Why was something decided? | `decisions.jsonl`, `02-design.md` |
| Why did it fail/retry/stop? | `events.jsonl` |
| What did an agent see and answer? | `agents/` |
| Was the record or config tampered with? | event-chain verification; config hash vs released version |

---

### 11.1 Central audit store [DECIDED]

Run records must not live only on one engineer's laptop. The orchestrator **publishes them
automatically** — no manual step — to a central audit repo.

- **Where (prototype):** a dedicated private git repo, `orchestrator-audit`, configured once
  in the global config. Layout mirrors the local one: `<project>/<run-id>/`.
- **When (automatic):**
  - at every **approval pause** (the run may wait hours; the record up to that point is safe), and
  - at the **end of every run**, whatever the outcome — completed, failed, stopped or rejected.
    Failed and stopped runs are the ones people most need to see.
- **How:** the orchestrator copies the run record into its local clone of the audit repo,
  commits (`<run-id>: <event>`), and pushes. Each publish is a new commit, so the audit repo's
  history shows how the record evolved.
- **Append-only:** the audit repo's `main` is protected — no force-push, no deletion — so
  history cannot be rewritten. Combined with the hash-chained event log, any later edit to a
  record is detectable.
- **Visible in normal review:** `pr-description.md` links to the run's folder in the audit
  repo, so every PR reviewer sees the audit trail as part of the review.
- **If publishing fails** (e.g. no network): the run is not blocked; the record is marked
  `unpublished` in `index.jsonl` and the next orchestrator command retries (retry: SHOULD).
- **Limitation (documented):** pushes use the engineer's git credentials, so a determined
  operator could still push misleading records — the hash chain makes this detectable, not
  impossible. **Production path:** write-once object storage (e.g. S3 Object Lock) or an audit
  service, fed by the central runner (§5.1).

## 12. Demonstration scenarios [DECIDED]

| Scenario | Project | Workspace starts from | Requirement | Must demonstrate |
|---|---|---|---|---|
| Greenfield | `shortener-greenfield-by-agents` (new repo with only `.orchestrator/`) | Approved template | Shorten, redirect, 404 for unknown codes | Full graph; S2 skipped; architecture created; design approval; parallel S5/S7; per-task commits; test + coverage gate |
| Brownfield | `url-shortener-ai-assisted` | Tag `baseline-greenfield` | Add click analytics | Baseline check; impact analysis; FR numbering continues; architecture updated; migration → change-control approval; retry after a gate failure |
| Ambiguous | `url-shortener-ai-assisted` | Tag `baseline-greenfield` | "Links should expire" | Blocking questions → clarification → answers in lineage; design rejection → re-plan |

Showcase run records are copied to `evidence/runs/` in the orchestrator repo.

---

## 13. Non-functional requirements

- Windows and Linux; Python 3.11+.
- Mock executor: required for tests and CI; also lets reviewers run all scenarios without Claude.
- No credentials stored by the orchestrator.
- Deterministic tests; engine independent of executor, config format, storage and runtime location.

---

## 14. Out of scope
Automatic merging (by design); web UI; multi-user auth/RBAC; distributed execution; more than
one active run per project; deploying the target service; cost computation.

---

## 15. Assumptions
- A-1 Claude Code installed and authenticated locally for real runs.
- A-2 Targets are Python repos with `scripts/check.py` and pytest.
- A-3 One engineer acts as operator and approver in the prototype.
- A-4 Target repos reachable with local git credentials.
- A-5 Agent output is non-deterministic; decisions are reproducible from the record, not by re-running agents.

---

## 16. Decided — summary

| # | Decision |
|---|---|
| D-1 | Orchestrator and target in separate repos; project ID = repo name |
| D-2 | Platform team owns and maintains the orchestrator and all global rules; project teams only use it and own `.orchestrator/` (scenarios, approved deps) in their product repo; project hardening is COULD |
| D-3 | Project config read from target `main`; code starts from scenario base ref |
| D-4 | Agents write only in `ORCH_HOME/workspaces/<project>/<run-id>/`; records owned by the orchestrator |
| D-5 | All work on `run/<run-id>`; never `main`; orchestrator commits and pushes; engineer raises PR; approver merges |
| D-6 | Merge-time enforcement by target CI + branch protection is the authoritative control |
| D-7 | Tamper evidence: orchestrator version + config hash recorded and shown in PR; hash-chained events |
| D-8 | Requirement folder per REQ; `00-source.md` immutable; per-task commits with trailers |
| D-9 | S2 for every existing codebase; S3 creates/updates architecture per significance criteria |
| D-10 | S5a code + unit tests per task; S5b acceptance tests from ACs; path partitioning |
| D-11 | S6: all tests pass, coverage ≥ 85%, enforced by the orchestrator |
| D-12 | S7a limited to docs paths; S7b high findings loop back to S5a (bounded) |
| D-13 | Checkpoints: Design + Release always; Clarification + Change control conditional |
| D-14 | `failed` = work unacceptable; `stopped` = safety/control halt |
| D-15 | Agent profiles per role, least privilege |
| D-16 | Mock executor with recorded fixtures |
| D-17 | Local CLI for the prototype; central runner as production path |
| D-18 | One active run per project (lock) |
| D-19 | Phase 1 = all MUST items, built and working before Phase 2 |
| D-20 | Run records published automatically to a central audit repo at every approval pause and at run end; linked from every PR |

---

## 17. Open — for the architecture proposal

| # | Question |
|---|---|
| O-1 | Graph execution engine: LangGraph vs custom lightweight engine |
| O-2 | State storage: JSON/JSONL files vs SQLite |
| O-3 | Config format: TOML (stdlib `tomllib`) vs YAML (PyYAML) |
| O-4 | Agent output contract: `claude -p` JSON output + pydantic vs fenced JSON |
| O-5 | Parallel execution: threads vs asyncio vs subprocess pool |
| O-6 | Workspace confinement for `claude -p`: tool/dir restrictions vs post-stage checks vs both |
| O-7 | Policy expression: Python policy classes vs declarative rules |
| O-8 | Mock fixtures: recorded from real runs vs hand-written |
| O-9 | Module layout of `src/orchestrator/` |
| O-10 | Applying profiles to `claude -p`: rendered system prompt + flags vs Claude Code subagent/skill files |

---

## 18. Risks

| Risk | Mitigation |
|---|---|
| Non-deterministic agents → flaky demo | Mock mode; showcase runs recorded once |
| Hallucinated files/APIs | S2 existence check |
| Prompt injection via repo content | Enforcement outside agents |
| Agent oversteps paths or weakens gates | Path partitioning, protected paths, orchestrator-enforced thresholds |
| Operator bypasses local rules | Merge-time CI enforcement; tamper evidence |
| Parallel contract mismatch | S3 contracts; bounded S5a loop |
| Runaway time/cost | Timeouts, max calls, max duration, safe-stop |
| Per-task execution makes runs slow | Mock mode for iteration; real runs only for showcase |
| Scope larger than time | Phase 1 first; everything else documented |

---

## 19. Assignment coverage

| Assignment requirement | Where |
|---|---|
| Explicit dependency graph with entry/exit gates | §7, C4, C5 |
| Sequential and parallel paths with synchronisation | §7 (S5, S7 joins), §7.3 |
| Cross-stage context and decision lineage | C10, §7.2 |
| Human approval for high-impact actions | C7, C6 |
| Bounded retries, fallback, rollback, safe-stop | C9, §6.2 |
| Policy guardrails: security, compliance, change control | C6, §9, §5.2 |
| Audit-grade observability and traceability | C12, §7.2, §11 |
| Reliability metrics | C13 |
| Dynamic re-planning with governance | C11 |
| Requirement understanding, decomposition, codebase reasoning | S1, S4, S2 |
| Production-quality outputs, tests, docs | S5a/S5b/S7a + S6 gate; C15 |
| Controlled autonomy | Stage boundaries, profiles, approvals, policies |
| Safe change management | §6.3, C6, §5.2 |
| Three scenarios | §12 |
