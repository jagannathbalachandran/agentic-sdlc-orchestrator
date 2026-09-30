# Engineering Summary — Agentic SDLC Orchestrator

This is the final engineering summary for Assignment 2. It covers the plan and
rationale, the artifacts, results, how the work was validated, risks and
trade-offs, assumptions, and limitations. Detailed design lives in
`docs/requirements.md`, `docs/architecture-proposal.md`,
`docs/architecture.md` and `docs/adr/ADR-001-orchestrator-architecture.md`;
the build history is in `docs/build-notes.md` and `AI_LOG.md`; the evidence of
real runs is in `evidence/runs/README.md`.

---

## 1. What was built

A command-line **orchestrator** that takes a software requirement for a target
project and drives it through a governed SDLC using AI agents (`claude -p`),
from requirements to a release-ready branch.

- The orchestrator is the machine; the **target project lives in its own
  repo**. Agents work in a disposable workspace on a `run/<run-id>` branch —
  never on `main`.
- **Agents execute work inside stages; the orchestrator controls everything
  between stages** — order, gates, policies, approvals, retries, rollback and
  audit.
- Principle, applied literally: **agents propose, humans approve and merge.**

### Stage graph

```
S0 Prepare → S1 Requirements ─(blocking questions?)→ [Clarification]
          → S2 Codebase analysis (skipped for greenfield)
          → S3 Design → [Design approval]
          → S4 Plan
          → S5a Implement + unit tests (one call and one commit per task) ┐ parallel
            S5b Acceptance tests (from ACs, not from the code)            ┘ join
          → S6 Verify (real tests, coverage ≥ 85%, lint, types, audit, policies)
               ├ gate failure → one fix call → re-verify (max 3)
               └ risky change → [Change-control approval]
          → S7a Docs ┐ parallel
            S7b Review ┘ join   (high-severity finding → fix → re-verify, max 2)
          → S8 Release readiness → [Release approval] → push run branch
```

### How it maps to the brief's core requirement 4 (workflow orchestration)

| Brief asks for | How it is met |
|---|---|
| Explicit dependency graph with entry/exit gates | Fixed global graph of `StageSpec`s; every stage has entry and exit gates recorded as events |
| Sequential and parallel paths with synchronisation | S5a/S5b and S7a/S7b run as parallel threads with joins; all git and event-log writes serialised through one lock |
| Cross-stage context and decision lineage | Chain: frozen source → FRs → DDs → tasks → commits → tests; `decisions.jsonl` |
| Human approval for high-impact actions | Four checkpoints: Clarification, Design, Change-control, Release |
| Bounded retries, fallback, rollback, safe-stop | Per-stage retry limits with feedback (fresh budget after a human re-plan); fallback to human; rollback to last checkpoint; `stop`, max duration, max calls, critical policy violation |
| Policy guardrails (security, compliance, change control) | 8 policies: workspace confinement, path partitioning, protected paths, main protection, secret scan, schema change control, diff-size limit, dependency control |
| Audit-grade observability and traceability | Hash-chained `events.jsonl`; agent transcripts; per-task commits with git trailers; generated `traceability.md`; run record per run |
| Reliability metrics | `metrics.json` computed from events only: success, first-pass rate, retries, rollbacks, MTTR, latency with and without human wait |
| Dynamic re-planning under governance | Rejecting the design with feedback invalidates S3 onward and re-runs it with the feedback, through the same gates and approval |

---

## 2. Plan and rationale

### Key decisions (made in consultation with Claude chat; recorded in ADR-001)

| Decision | Rationale |
|---|---|
| Orchestrator and targets in separate repos; platform team owns global rules | Matches how a real platform would be run; project teams can't weaken gates locally |
| Heavy up-front investment in requirements (~3h) | Clear acceptance criteria made bounded agent autonomy possible and gave every task a testable definition of done |
| Custom lightweight engine, not LangGraph | Graph is fixed; run-record format was already decided — a library would add a second persistence model |
| Flat JSON/JSONL files, TOML config, threads | Zero new dependencies; enough for prototype scale |
| Stateless pause/resume | Every CLI command reloads state from disk and drives to the next pause; proven by a multi-process test |
| Agents write files with their tools and return a small JSON summary; gates read the files | Matches how Claude Code works; one simple contract; validated in the P0 spike |
| Post-stage confinement check is the real enforcement | The P0 spike showed `--add-dir` gives no real boundary and `--restricted` behaves like model judgement |
| Vertical slice to real runs, not a mock-only build | The brief grades realism of outputs and the scenarios; specific items trimmed and listed below |

### Process

1. Requirements (with Claude chat), then requirements rev 2 against the brief.
2. Architecture proposal by Claude Code, two review rounds.
3. `claude -p` feasibility spike (P0) before building the executor.
4. Build in tasks (T1–T9) with **three hard stops** for human review.
5. Integration audit before any real run.
6. Real runs with the human as approver; each failure diagnosed and fixed;
   then an automated verification run to confirm the fixes end to end.

---

## 3. Artifacts

| Artifact | Location |
|---|---|
| Requirements (rev 2) | `docs/requirements.md` |
| Architecture proposal (analysis, O-1..O-10, build plan, limitations) | `docs/architecture-proposal.md` |
| Architecture overview | `docs/architecture.md` |
| Architecture decision record | `docs/adr/ADR-001-orchestrator-architecture.md` |
| Feasibility spike | `docs/spikes/` |
| Task plan and build log (incl. integration audit table) | `docs/tasks.md`, `docs/build-notes.md` |
| AI usage log | `AI_LOG.md` |
| Orchestrator source and tests | `src/orchestrator/`, `tests/` |
| Global config, agent profiles, greenfield template | `config/`, `agents/profiles/`, `templates/python-service/` |
| **Real-run evidence (runs, findings, fixes, completed run's outputs)** | `evidence/runs/` — start with `evidence/runs/README.md` |
| Target repos | `shortener-greenfield-by-agents`, `url-shortener-brownfield-target` (copy of Assignment 1; Assignment 1 itself untouched) — configuration only |

---

## 4. Results

| Run | Approvals | Got as far as | Outcome | Root cause | Fix |
|---|---|---|---|---|---|
| `greenfield-minimal-20260930-001` | Human (design rejected with feedback) | S3 re-run after rejection | failed | Rejection feedback never reached the re-run; re-plan inherited an exhausted retry budget | `adf9550` and related |
| `greenfield-minimal-20260930-002` | Human (design approved) | S5a, before any agent call | failed | S5a's plan parser had drifted from the S4 gate's parser | `5b51f29` |
| `greenfield-minimal-20260930-003` | Human (design approved) | S5a, during developer calls | failed | Plan parser kept only the first line of each task, so the developer got truncated instructions | `c7ed024` |
| Verification run (`verify-greenfield`) | **Automated**, labelled | **all 9 stages** | **completed** | — | `6fd9032`, `6dea461`, `0839ae4` found and fixed during the run |

**No human-approved real run reached Release in the time available.** After
the fixes from runs 001–003, an **automated verification run** with the real
executor — in a throwaway target, checkpoints approved automatically and
clearly labelled `claude-code-verification` — **completed end to end**: all
nine stages, real per-task commits with correct trailers, S6 recovering
through two real retries, and `traceability.md` generated. It exposed and
fixed three further bugs (path resolution, Windows text encoding,
traceability commit linking).

**Browse the completed run's requirements, design, plan, code, tests and
traceability:** `evidence/runs/README.md` → *Start here*.

**What the real runs demonstrated:** real requirements and designs with full
citation chains; S2 skipped for greenfield; pause/resume across processes;
human rejection with feedback and re-planning; the architect adding an
explicit technology stack after a human-driven rule change; the architect
choosing the standard library to stay within an empty approved-dependency
list; per-task developer calls and commits; parallel S5a/S5b; S6 recovering
from real test failures via fix calls; and precise diagnosis from events and
transcripts.

**Scope note:** the real runs used a reduced greenfield requirement (shorten
+ redirect, `REQ-2`) as a shakedown. The full greenfield scenario (with
reliability behaviours: input validation, 404 for unknown codes,
collision-free codes) is defined in `greenfield.toml`. **Brownfield and
ambiguous** scenarios are defined in the target repo but were not run for
real; their mechanisms (codebase analysis, change-control, fault injection,
clarification, design rejection) are covered by tests.

**Key lesson:** the mock-based test suite passed while every human-approved
real run failed — each time because parsing or gate logic had been tested
against fixture formats, not against what a real agent writes (titles in
headings, wrapped lines), and in the verification run because of Windows
text encoding and path handling. Each real run found the next issue; the run
record was enough to diagnose it.

---

## 5. Testing approach and validation

**Orchestrator's own tests**
- **335 tests passing, 1 skipped; 95.93% coverage** (threshold 85%).
- Unit tests for the engine, gates, policies, re-planning, metrics and audit;
  integration tests for multi-process pause/resume and the parallel scheduler
  against a real git repo; an end-to-end CLI test asserting every run
  artifact is produced.
- All tests run on the **mock executor** (no Claude, no network), per C15.
- Quality gate (`scripts/check.py`, also in CI): ruff, ruff format,
  mypy --strict, pytest with coverage ≥ 85%, pip-audit.

**Validation of the target code produced by agents**
- S6 runs the target's own `scripts/check.py` in the workspace venv: all tests
  pass, coverage ≥ 85% (threshold passed by the orchestrator, never trusted
  from target config), lint, types, dependency audit.
- Acceptance tests (S5b) are written from acceptance criteria and design
  contracts, independently of the implementation.
- Policies run on the run's full diff at S6.
- Merge-time CI on GitHub re-runs the gates; nothing reaches `main` without a
  human-reviewed PR.

**Validation of the build process itself**
- P0 spike before the executor was built.
- Three hard-stop reviews; each found real issues (see `AI_LOG.md`).
- An integration audit before real runs found components that were built and
  unit-tested but not wired into the CLI (S6 verification was still a stub).
- Real runs as the final check — see section 4 and `evidence/runs/README.md`.

---

## 6. Risks and trade-offs

| Risk | Mitigation | Residual |
|---|---|---|
| Non-deterministic agents → inconsistent results | Gates check real files and real test results, never agent self-assessment; human review at checkpoints | Runs vary; evidence is a recorded run, not a reproducible one |
| Agent writes outside its scope | Post-stage confinement check, path partitioning, protected paths; CLI restriction as a first layer | CLI restriction is not a hard boundary (P0) |
| Prompt injection via repo content | Enforcement lives outside agents | An agent could still produce misleading content; human review catches it |
| Agent weakens quality gates | Coverage threshold passed by the orchestrator; gate config files protected | — |
| Runaway time or cost | Per-call timeout (process tree killed), per-call budget cap, max calls, max duration | — |
| Operator bypasses local rules | Merge-time CI + branch protection; version and config hash recorded | A local tool can't stop its own operator — made detectable, not impossible |
| Mock tests pass but real integration fails | Integration audit; end-to-end CLI test; real runs | **Confirmed:** every real run failed on agent-output format or platform issues the tests had missed |

**Main trade-offs**
- **Vertical slice over breadth:** real runs and traceability were prioritised
  over building every SHOULD item.
- **Custom engine over a framework:** more code to own, but one persistence
  model and no heavy dependency.
- **Flat files over a database:** simple and inspectable; not built for many
  concurrent runs.
- **One call per plan task in S5a:** slower and costlier runs, but real
  per-task commits and a working backward trace.
- **Stopping real runs at a fixed time:** submitted with diagnosed failures
  and one completed verification run rather than rushing past quality checks.

---

## 7. Assumptions

- Claude Code is installed and authenticated for real runs (A-1).
- Targets are Python repos with `scripts/check.py` and pytest (A-2).
- One engineer acts as operator and approver in the prototype (A-3).
- Target repos are reachable with local git credentials (A-4).
- Agent output is non-deterministic; decisions are reproducible from the
  record, not by re-running agents (A-5).
- Workspace confinement relies on the post-stage check, since `claude -p`'s own
  restriction was not shown to be a hard boundary (O-6, partially assumed).
- Workspaces must not live under OS temp paths — `claude -p` silently refuses
  writes there (found in T4.1).

---

## 8. Limitations

### Results

- **No human-approved real run reached Release** in the time available; the
  complete flow was demonstrated by an automated verification run with real
  agents (approvals automated and labelled) and by the mock end-to-end test.
- **Brownfield and ambiguous scenarios were not run for real.**
- The real runs used a reduced greenfield requirement (shorten + redirect).

### Built differently from the design, or partially

- **Re-planning** covers design rejection only; re-planning after a rejected
  Change-control or Release approval is designed (G-9) but not built —
  rejecting those ends the run.
- **traceability.md** is generated after the final S8 commit and is not
  committed to the run branch (no separate Join S7 stage), so it would not be
  merged with the code as §7.2 intends. S7b's review findings are likewise
  written to the workspace but not committed.
- **Duration and call limits** are simple fixed checks.
- **Output schema gate** for agent documents is still a stub; content is
  checked by the citation, technology-stack and S6 command gates instead.
- **Single S6 command gate** runs all checks through the target's
  `scripts/check.py`, rather than five separately configurable gates.
- **Flat file layout:** requirement documents live in the workspace root, not
  in `docs/requirements/REQ-…/` as the design specifies.
- **Local-path targets:** run branches are pushed to the local target clone;
  the operator pushes them to GitHub.
- **Lock gap:** a small window between resolving a checkpoint and continuing,
  where another process could in theory take the project lock.
- **Workspace confinement:** the CLI's restriction flags are not a hard
  boundary; the post-stage check is the enforcement.
- **Mock fixtures** were not derived from the real runs (D-21); the mock
  executor uses generic fixtures.
- **Metrics** are per run; there is no aggregation across runs.
  `retry_count` includes re-plans after a human rejection.
- **One regression test** (traceability commit linking, `0839ae4`) is skipped
  as timing-sensitive on the development machine; the fix itself was confirmed
  by the completed verification run.

### SHOULD items not built (requirements §2)

- Automatic publishing of run records to a central audit repo, re-publishing
  and the audit-repo link in the PR description.
- Audit-record check in the target's CI.
- Resume after a process is killed mid-stage (resume at checkpoints works).
- `status` command with merged detection; `abandon`.

### COULD items (documented only)

Project-level hardening of global rules; stale-branch detection; automatic PR
creation; central thresholds via a reusable CI workflow; central runner
deployment; git-worktree isolation for parallel stages; OpenTelemetry export.

---

## 9. How AI was used

- **Me — research and framing:** I started by researching the problem space,
  deep-diving into the brief and brainstorming the approach myself: the
  high-level requirements, constraints, governance principles (agents
  propose, humans approve), the separation of orchestrator and target
  repos, and the scope. I then refined these in discussion with Claude chat.
- **Claude chat — discussion partner and reviewer:** used to challenge and
  refine my requirements, architecture and scope decisions, draft documents
  from them, and act as a second reviewer at each hard stop and during the
  real runs.
- **Claude Code — analysis and implementation:** architecture proposal, ADR
  draft, feasibility spike, implementation task by task with tests and
  per-task commits, diagnosis and fixes after each real run, and — at my
  instruction — the automated verification run.
- **Me — oversight and decisions:** approvals at hard stops and at every
  checkpoint of runs 001–003, local verification, target-repo setup, and all
  scope decisions.

Full detail, including agent mistakes and corrections, is in `AI_LOG.md`.