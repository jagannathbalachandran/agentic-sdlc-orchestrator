# agentic-sdlc-orchestrator

An agentic orchestration layer that drives Python software projects through the
full SDLC — requirements, design, implementation, testing, documentation and
release readiness — with governance: quality gates, policy guardrails, human
approval checkpoints and a complete audit trail.

Agents (`claude -p`) do the work **inside** stages. The orchestrator controls
everything **between** stages: order, entry/exit gates, policies, human
approvals, retries, rollback and a tamper-evident audit trail.
**Agents propose; humans approve and merge.**

- **Results and evidence of real runs:** [`evidence/runs/README.md`](evidence/runs/README.md) — start with *Start here*
- Engineering summary (results, risks, limitations): [`docs/engineering-summary.md`](docs/engineering-summary.md)
- Architecture overview: [`docs/architecture.md`](docs/architecture.md)
- Module/class reference, flow diagrams and a line-by-line E2E walkthrough: [`docs/internals.md`](docs/internals.md)
- Requirements: [`docs/requirements.md`](docs/requirements.md)
- Decision record: [`docs/adr/ADR-001-orchestrator-architecture.md`](docs/adr/ADR-001-orchestrator-architecture.md)
- AI usage log: [`AI_LOG.md`](AI_LOG.md)

---

## Results at a glance

- **A full run completed end to end with real agents** (greenfield,
  shorten + redirect): all nine stages, real per-task commits with
  `Task`/`FR`/`Req` trailers, S6 passing after two real fix-and-retry
  cycles, and a generated traceability table. This was an automated
  verification run — checkpoints approved automatically and labelled as
  such. Browse what the agents produced:
  [requirements](evidence/runs/VERIFY-verify-greenfield-greenfield-minimal-20260930-001/workspace/01-requirements.md) ·
  [design](evidence/runs/VERIFY-verify-greenfield-greenfield-minimal-20260930-001/workspace/02-design.md) ·
  [plan](evidence/runs/VERIFY-verify-greenfield-greenfield-minimal-20260930-001/workspace/03-plan.md) ·
  [code](evidence/runs/VERIFY-verify-greenfield-greenfield-minimal-20260930-001/workspace/src) ·
  [tests](evidence/runs/VERIFY-verify-greenfield-greenfield-minimal-20260930-001/workspace/tests) ·
  [traceability](evidence/runs/VERIFY-verify-greenfield-greenfield-minimal-20260930-001/workspace/traceability.md) ·
  [commits](evidence/runs/VERIFY-verify-greenfield-greenfield-minimal-20260930-001/commits-with-trailers.txt)
- **Three human-approved real runs** (I approved or rejected at each
  checkpoint) each exposed an integration bug the mock-based tests had
  missed; each was diagnosed from the run record and fixed before the next
  run. None reached Release in the time available.
- **335 tests passing (1 skipped), 95.93% coverage**; ruff, mypy --strict and
  pip-audit clean.
- Brownfield and ambiguous scenarios are defined but were not run for real.

---

## 1. How it works (in one picture)

```
S0 Prepare → S1 Requirements ─(blocking questions?)→ [Clarification]
          → S2 Codebase analysis (skipped for greenfield)
          → S3 Design → [Design approval]
          → S4 Plan
          → S5a Implement + unit tests (one commit per task) ┐ parallel
            S5b Acceptance tests                             ┘ join
          → S6 Verify (tests, coverage ≥ 85%, lint, types, audit, policies)
               └ risky change → [Change-control approval]
          → S7a Docs ┐ parallel
            S7b Review ┘ join
          → S8 Release readiness → [Release approval] → push run branch
```

- The **orchestrator repo** (this repo) is owned by the platform team: engine,
  global stage graph, gates, policies, agent profiles, greenfield template.
- Each **target repo** is owned by its project team and holds only its inputs
  under `.orchestrator/`: project config and scenarios.
- Every run works in a disposable **workspace** — built from the approved
  template (greenfield) or cloned from the target (existing code) — on a
  `run/<run-id>` branch. Nothing is ever committed to `main`.

---

## 2. Orchestrator repo vs target repo

| | Orchestrator repo (this repo) | Target repo |
|---|---|---|
| **What it is** | The machine: engine, stage graph, gates, policies, agent profiles, greenfield template | The product being built or changed (e.g. a URL shortener) |
| **Owned by** | Platform team | Project team |
| **What goes in it** | Orchestrator code and global rules — never project code | The product's code, plus an `.orchestrator/` folder with its inputs |
| **Changed by a run?** | No | Yes — a run adds a `run/<run-id>` branch; a human merges it via PR |

A **target repo** is any Git repo the orchestrator works on. It only needs:

```
<target-repo>/
└── .orchestrator/
    ├── project.toml              # project name + approved dependencies
    └── scenarios/
        └── <scenario-id>.toml    # one file per requirement to deliver
```

- **Greenfield target:** an empty repo containing only `.orchestrator/`; the
  first run builds the product from the approved template.
- **Existing (brownfield) target:** a repo with existing code; scenarios name a
  `base_ref` (tag or commit) the run starts from.

The orchestrator never edits the target's `main`. It prepares a disposable
**workspace** (from the template, or a clone of the target), works on a
`run/<run-id>` branch, and pushes that branch after Release approval. Project
teams never modify the orchestrator; they only add scenarios to their own
repo.

---

## 3. Prerequisites

- Python 3.11+
- Git
- [Claude Code](https://docs.claude.com) installed and logged in — **only for
  real runs**. Mock runs and all tests need no Claude and no network.
- macOS/Linux only, optional: [`jq`](https://jqlang.github.io/jq/) for the
  JSON inspection commands below (or use `python -m json.tool <file>`).

---

## 4. Setup

**Windows (PowerShell)**

```powershell
git clone <this repo> agentic-sdlc-orchestrator
cd agentic-sdlc-orchestrator
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

**macOS/Linux (bash)**

```bash
git clone <this repo> agentic-sdlc-orchestrator
cd agentic-sdlc-orchestrator
python -m venv .venv
source .venv/bin/activate          # Git Bash on Windows: source .venv/Scripts/activate
pip install -e ".[dev]"
```

### Running the gates

**`pip install -e ".[dev]"` (above) must be run first.** In a fresh venv
without it, `pytest` cannot import the `orchestrator` package the tests
exercise — `scripts/check.py` fails at the pytest gate during test
collection, before any test actually runs.

```bash
python scripts/check.py            # same command on every platform
```

This runs `ruff check`, `ruff format --check`, `mypy --strict`, `pytest`
(with coverage ≥ 85%) and `pip-audit`, stopping at the first failing gate.

### The CLI

After installing, the CLI is available as `orchestrator` on every platform. If
that command is not on your PATH, use `python -m orchestrator.cli.main`
instead — the arguments are identical. Every command supports `--help`.

---

## 5. Where things are stored

The orchestrator keeps its runtime data in `ORCH_HOME`, by default
`~/.orchestrator` (macOS/Linux) or `%USERPROFILE%\.orchestrator` (Windows):

```
.orchestrator/
├── projects.json                         # registry: project name → repo location
├── workspaces/<project>/<run-id>/        # the run's workspace (agents write here)
└── runs/<project>/<run-id>/              # the run record (orchestrator only)
```

Override with the `ORCH_HOME` environment variable or `--orch-home <path>`.

> **Do not put `ORCH_HOME` under an OS temp directory** (e.g. `%TEMP%`,
> `/tmp`) for real runs: `claude -p` silently refuses to write there.

---

## 6. Using the orchestrator

The `orchestrator` and `git` commands are the same on every platform and are
shown once. Where helper commands differ, each block is shown for **Windows
(PowerShell)** and **macOS/Linux (bash)**.

### 6.1 Prepare a target repo (project team)

A target repo needs a `.orchestrator/` folder on its `main` branch.

**Project config** — `.orchestrator/project.toml`:

```toml
project_name = "shortener-greenfield-by-agents"   # descriptive only; not matched against anything
approved_dependencies = []                        # new deps outside this list need change-control approval
```

**A scenario** — `.orchestrator/scenarios/<scenario-id>.toml`:

```toml
scenario_id = "greenfield-minimal"
req_id = "REQ-2"
requirement_text = """
Build a minimal URL shortener with two capabilities only:
- Shorten: POST /shorten accepts a long URL and returns a short code.
- Redirect: GET /{code} redirects to the original URL.
"""
# For an existing codebase, add the ref the run starts from:
# base_ref = "baseline-greenfield"
# Optional: force one recoverable S6 failure to demonstrate retry (recorded as injected):
# inject_fault = true
```

- **Greenfield:** omit `base_ref`; the workspace is built from
  `templates/python-service/`.
- **Existing codebase:** set `base_ref` to a tag or commit; the workspace is a
  clone at that ref. Config is always read from the target's `main`.

Commit and push the files to the target's `main` (all platforms):

```bash
git add .orchestrator
git commit -m "Add orchestrator project config and scenario"
git push
```

### 6.2 Register the project (once)

**Windows (PowerShell)**

```powershell
orchestrator register shortener-greenfield-by-agents C:\Users\<you>\projects\shortener-greenfield-by-agents
```

**macOS/Linux (bash)**

```bash
orchestrator register shortener-greenfield-by-agents ~/projects/shortener-greenfield-by-agents
```

General form: `orchestrator register <project-name> <repo-location>`. The
registry maps the project name to the repo location; runs read scenarios from
that repo's `main`.

### 6.3 Validate before running

Checks TOML syntax, required fields, ID formats, the project config, and that
the project is registered. Prints `OK` or the errors. No agents are called.

**Windows (PowerShell)**

```powershell
orchestrator validate <project-name> `
  --defaults config\defaults.toml `
  --project-config <target-repo>\.orchestrator\project.toml `
  --scenario-config <target-repo>\.orchestrator\scenarios\<scenario-id>.toml
```

**macOS/Linux (bash)**

```bash
orchestrator validate <project-name> \
  --defaults config/defaults.toml \
  --project-config <target-repo>/.orchestrator/project.toml \
  --scenario-config <target-repo>/.orchestrator/scenarios/<scenario-id>.toml
```

### 6.4 Start a run

All platforms:

```bash
# Real run (default): real claude -p agents
orchestrator run <project-name> <scenario-id> --operator <your-name>

# Mock run: recorded/generic agent responses, no Claude, no network
orchestrator run <project-name> <scenario-id> --operator <your-name> --mock
```

The command drives the run until it reaches an approval checkpoint or
finishes, then exits and prints the status and `run-id`, for example:

```
run greenfield-minimal-20260930-002: awaiting_approval (design)
run-id=greenfield-minimal-20260930-002
```

Set shortcuts to the run's workspace and record, used by the commands below:

**Windows (PowerShell)**

```powershell
$runId = "<run-id>"
$ws  = "$env:USERPROFILE\.orchestrator\workspaces\<project-name>\$runId"
$rec = "$env:USERPROFILE\.orchestrator\runs\<project-name>\$runId"
```

**macOS/Linux (bash)**

```bash
runId=<run-id>
ws=~/.orchestrator/workspaces/<project-name>/$runId
rec=~/.orchestrator/runs/<project-name>/$runId
```

### 6.5 Follow progress

**Windows (PowerShell)**

```powershell
# Watch events live (Ctrl+C stops watching, not the run)
Get-Content "$rec\events.jsonl" -Wait -Tail 5

# Status of every stage
$g = (Get-Content "$rec\graph.json" | ConvertFrom-Json).stages
$g.PSObject.Properties | ForEach-Object { $_.Value } | Select-Object stage_id, status, attempts | Format-Table

# Where the run is paused
Get-Content "$rec\graph.json" | ConvertFrom-Json | Select-Object terminal_state, pending_checkpoint
```

**macOS/Linux (bash)**

```bash
# Watch events live (Ctrl+C stops watching, not the run)
tail -f -n 5 "$rec/events.jsonl"

# Status of every stage
jq -r '.stages[] | "\(.stage_id)  \(.status)  \(.attempts)"' "$rec/graph.json"

# Where the run is paused
jq '{terminal_state, pending_checkpoint}' "$rec/graph.json"
```

### 6.6 Review and decide at each checkpoint

| Checkpoint | When | Review | Then |
|---|---|---|---|
| Clarification | S1 raised blocking questions | Questions printed by the command | `answer` |
| Design | After S3 (always) | `01-requirements.md`, `02-design.md` in the workspace | `approve` or `reject` |
| Change-control | S6 found a risky change (migration, new dependency, large diff) | Policy events in `events.jsonl`, the diff in the workspace | `approve` or `reject` |
| Release | After S8 (always) | `03-plan.md`, `report.md`, commits in the workspace | `approve` or `reject` |

Review what the agents produced:

**Windows (PowerShell)**

```powershell
Get-Content -Encoding UTF8 "$ws\01-requirements.md"
Get-Content -Encoding UTF8 "$ws\02-design.md"
Get-Content -Encoding UTF8 "$ws\03-plan.md"
Get-Content -Encoding UTF8 "$rec\report.md"
git -C $ws log --format="%h %s%n%(trailers)" -20
```

**macOS/Linux (bash)**

```bash
cat "$ws/01-requirements.md"
cat "$ws/02-design.md"
cat "$ws/03-plan.md"
cat "$rec/report.md"
git -C "$ws" log --format="%h %s%n%(trailers)" -20
```

Then decide (all platforms):

```bash
# Approve — continues to the next checkpoint or completion
orchestrator approve <project-name> <run-id> --comment "<why>" --approver <your-name>

# Reject with feedback — re-plans (Design: re-runs S3 onward with your feedback)
orchestrator reject <project-name> <run-id> --comment "<what to change>" --approver <your-name>

# Reject and end the run
orchestrator reject <project-name> <run-id> --comment "<why>" --approver <your-name> --final

# Answer clarification questions — S1 re-runs with your answers
orchestrator answer <project-name> <run-id> --comment "<answers>" --approver <your-name>
```

### 6.7 Stop or roll back

All platforms:

```bash
# Stop a run safely (no partial commit)
orchestrator stop <project-name> <run-id> --reason "<why>"

# Reset the workspace to the last checkpoint commit (discards later commits)
orchestrator rollback <project-name> <run-id>
```

### 6.8 List and inspect runs

There is no dedicated `runs list`/`runs show` command — inspect the run
record directly under `ORCH_HOME` (§5).

**Windows (PowerShell)**

```powershell
# List every run recorded for a project
Get-ChildItem "$env:USERPROFILE\.orchestrator\runs\<project-name>" -Directory

# Inspect one run
Get-Content "$rec\run.json" | ConvertFrom-Json
```

**macOS/Linux (bash)**

```bash
# List every run recorded for a project
ls ~/.orchestrator/runs/<project-name>

# Inspect one run
jq . "$rec/run.json"
```

### 6.9 After a run completes

On Release approval the orchestrator pushes `run/<run-id>` to the target
repo's `origin`. For targets registered by **local path**, that is the local
clone — push it to GitHub yourself (all platforms):

```bash
cd <target-repo>
git push origin run/<run-id>
```

Then **raise a PR** into `main` using the generated `pr-description.md` in the
run record. The approver reviews and merges; the target's CI re-runs the gates
on the merge result. The orchestrator never merges.

### 6.10 View a run's metrics and report

Every run gets its own metrics. `metrics.json` is computed **from the run's
events only** and written to the run record whenever the run reaches a final
state — completed, failed, stopped or rejected — so failed runs have metrics
too. `report.md` (with a metrics table) is written at S8, before Release
approval.

**Windows (PowerShell)**

```powershell
# All metrics for one run
Get-Content "$rec\metrics.json" | ConvertFrom-Json

# Human-readable report
Get-Content -Encoding UTF8 "$rec\report.md"

# Compare runs of a project side by side
Get-ChildItem "$env:USERPROFILE\.orchestrator\runs\<project-name>" -Directory | ForEach-Object {
  $m = Get-Content "$($_.FullName)\metrics.json" -ErrorAction SilentlyContinue | ConvertFrom-Json
  [pscustomobject]@{ run = $_.Name; success = $m.run_success; retries = $m.retry_count;
                     e2e_s = $m.end_to_end_latency_seconds; human_wait_s = $m.human_wait_seconds }
} | Format-Table
```

**macOS/Linux (bash)**

```bash
# All metrics for one run
jq . "$rec/metrics.json"

# Human-readable report
cat "$rec/report.md"

# Compare runs of a project side by side
for d in ~/.orchestrator/runs/<project-name>/*/; do
  echo "$(basename "$d"): $(jq -c '{run_success, retry_count, end_to_end_latency_seconds, human_wait_seconds}' "$d/metrics.json" 2>/dev/null)"
done
```

| Metric | Meaning |
|---|---|
| `run_success` | Whether the run completed (true), failed or stopped (false), or is still in progress (null) |
| `stage_first_pass_rate` | Share of stages that passed on their first attempt (skipped stages excluded) |
| `retry_count`, `rollback_count` | Retries (including re-plans after a human rejection) and rollbacks during the run |
| `mttr_seconds` | Mean time from a stage failing to that stage next succeeding |
| `end_to_end_latency_seconds` | Total wall-clock time of the run |
| `human_wait_seconds` | Time spent waiting at approval checkpoints |
| `end_to_end_latency_excluding_human_wait_seconds` | Run time with human waiting removed |
| `stage_latency_seconds`, `agent_call_latency_seconds` | Time per stage (all attempts) and per agent call |

Metrics are **per run**. There is no built-in aggregation across runs (for
example a project-wide success rate over time); the comparison commands above
are a manual way to do it.

---

## 7. What a run produces

**Run record** — `runs/<project>/<run-id>/`, written only by the orchestrator:

| File | Contents |
|---|---|
| `run.json` | IDs, operator, times, outcome, base commit, run branch, orchestrator version, effective-config hash, scenario hash |
| `scenario.json` | Snapshot of the scenario the run started from (hashed into `run.json`) |
| `config.effective.json` | The merged configuration used (hashed into `run.json`) |
| `graph.json` | Per-stage status, attempts, commits |
| `artifacts/<stage>/` | Content-hashed copy of each stage's own output files |
| `events.jsonl` | Hash-chained audit log: every transition, gate, policy result, approval, retry, stop |
| `approvals.jsonl`, `decisions.jsonl` | Approval records and decision lineage |
| `agents/` | Role, profile version, prompt and response for every agent call |
| `metrics.json` | Success, first-pass rate, retries, rollbacks, MTTR, latency with/without human wait |
| `report.md`, `pr-description.md` | Human-readable summary; ready-to-paste PR description |

**Workspace** — on the `run/<run-id>` branch, one commit per stage and one per
implementation task, each with git trailers (`Run`, `Stage`, `Task`, `FR`,
`Req`), plus `00-source.md` (frozen requirement), `01-requirements.md`,
`02-design.md`, `03-plan.md` and the generated `traceability.md`
(requirement → FR → AC → design → task → commit → test).

Trace any line of code back to its requirement (all platforms, run inside the
workspace):

```bash
git blame <file>                                   # find the commit
git log -1 --format="%(trailers)" <commit>         # Task / FR / Req
```

---

## 8. Demonstration scenarios

| Scenario | Target repo | Scenario id | Demonstrates |
|---|---|---|---|
| Greenfield | `shortener-greenfield-by-agents` | `greenfield` (full) / `greenfield-minimal` | Full graph, S2 skipped, design approval, parallel stages, per-task commits, test + coverage gate |
| Brownfield | `url-shortener-brownfield-target` (copy of Assignment 1) | `brownfield` | Baseline check, codebase analysis, migration → change-control approval, injected failure and fix |
| Ambiguous | `url-shortener-brownfield-target` | `ambiguous` | Blocking questions → clarification; design rejection → re-plan |

**Status at submission:** three human-approved real greenfield runs
(`greenfield-minimal-20260930-001` to `-003`) each exposed an integration bug
that the mock-based tests had not; each was diagnosed from the run record and
fixed. After those fixes, an automated verification run with real agents
(approvals automated and labelled) completed end to end. Brownfield and
ambiguous scenarios are defined but were not run for real in the time
available. Full account and browsable outputs:
[`evidence/runs/README.md`](evidence/runs/README.md).

---

## 9. Testing approach

- **All orchestrator tests run on the mock executor** — no Claude, no network,
  deterministic.
- **Unit tests** for the engine, gates, policies, retries, re-planning,
  metrics and audit.
- **Integration tests:** pause/resume across separate processes; the parallel
  scheduler against a real git repo; an end-to-end CLI test asserting every
  run artifact is produced.
- **Quality gate** (`scripts/check.py`, also run in CI): ruff, ruff format,
  mypy --strict, pytest with coverage ≥ 85%, pip-audit.
- **Real runs** are the final integration check (not part of the automated
  suite, since they need Claude and cost money). They found issues the
  automated suite could not — see [`evidence/runs/README.md`](evidence/runs/README.md).

---

## 10. Limitations

No human-approved real run reached Release in the time available; the full
flow was completed by an automated verification run with real agents (see
[Results at a glance](#results-at-a-glance)).

See section 8 of the [engineering summary](docs/engineering-summary.md) and
`docs/architecture-proposal.md` §4.3. Main ones: re-planning after
Change-control/Release rejection is not built; central audit-repo publishing
is not built (records stay local and in `evidence/runs/`); run branches for
local-path targets must be pushed to GitHub manually; workspace confinement
relies on a post-stage check; metrics are per run, with no built-in
aggregation across runs.