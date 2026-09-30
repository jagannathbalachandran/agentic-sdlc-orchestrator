# Architecture Overview — Agentic SDLC Orchestrator

How the orchestrator is built: its high-level architecture, the orchestration
model, control flow and key decisions. Full reasoning is in
`docs/architecture-proposal.md` and `docs/adr/ADR-001-orchestrator-architecture.md`.

---

## 1. High-level architecture

```
   Engineer / Approver
          │  run · approve · reject · answer · stop
          ▼
   ┌──────────────┐        ┌──────────────────────────────┐
   │     CLI      │───────►│            Engine            │
   └──────────────┘        │  stage graph · state machine │
                           │  scheduler · retries         │
                           └──┬──────────┬──────────┬─────┘
                              │          │          │
               ┌──────────────▼─┐  ┌─────▼──────┐  ┌▼──────────────────┐
               │   Executors    │  │ Governance │  │   Audit / Record   │
               │ real · mock    │  │ gates      │  │ events · approvals │
               │ + agent        │  │ policies   │  │ transcripts ·      │
               │   profiles     │  │ approvals  │  │ metrics · reports  │
               └───────┬────────┘  └─────┬──────┘  └────────────────────┘
                       │ claude -p       │ checks files & diffs
                       ▼                 ▼
               ┌──────────────────────────────────┐        ┌──────────────────┐
               │  Workspace (disposable clone)    │◄───────│   Target repo    │
               │  run/<run-id> branch             │ clone  │  .orchestrator/  │
               │  agents write here only          │───────►│  (config +       │
               └──────────────────────────────────┘  push  │   scenarios)     │
                                          after Release    └──────────────────┘
```

**Three ideas hold the design together:**

1. **Orchestrator and product are separate.** The orchestrator repo (platform
   team) holds the engine and the global rules. Each target repo (project
   team) holds the product and its inputs in `.orchestrator/`.
2. **Agents work inside stages; the orchestrator controls everything between
   them** — order, gates, policies, approvals, retries, audit.
3. **Agents propose, humans approve.** Agents only write files in the
   workspace. Only the orchestrator commits and pushes, only to a run branch,
   only after Release approval. A human merges.

---

## 2. How a run flows

```
S0 Prepare ─► S1 Requirements ─► S2 Codebase analysis ─► S3 Design ─► S4 Plan
                   │  (skipped for greenfield)       [Design approval]
          [Clarification]
          if questions
                                   ┌─► S5a Implement (one commit per task) ─┐
                           S4 ─────┤                                         ├─► S6 Verify
                                   └─► S5b Acceptance tests ─────────────────┘  [Change-control]
                                                                                 if risky
                                   ┌─► S7a Docs ───┐
                           S6 ─────┤               ├─► S8 Release ─► [Release approval] ─► push
                                   └─► S7b Review ─┘
```

- Each agent stage is one role: analyst, architect, planner, developer, test
  engineer, technical writer, reviewer. S0, S6 and S8 are run by the
  orchestrator itself.
- Every stage passes through the same pipeline:
  **entry gates → agent call → exit gates → events → commit**.
- Agents write their files with their own tools and return a small JSON
  summary. **Gates check the files, not the agent's claims.**

---

## 3. Components

| Component | Responsibility |
|---|---|
| **CLI** (`cli/`) | Commands for engineers and approvers; each one re-enters the engine |
| **Engine** (`engine/`) | Stage graph, state machine (`drive()`), parallel scheduler, retries, re-planning, project lock |
| **Executors** (`executors/`, `profiles/`) | Real (`claude -p`) and mock (recorded responses); seven agent profiles rendered into prompts and tool permissions |
| **Governance** (`gates/`, `policies/`) | Entry/exit gates, eight policies, approval checkpoints |
| **Workspace** (`workspace/`) | Template copy or clone, run branch, venv, serialised git, rollback |
| **Audit** (`audit/`) | Hash-chained events, run record, transcripts, traceability, metrics, report, PR description |
| **Config** (`config/`) | Global defaults, project config and scenarios (TOML, validated) |

---

## 4. Governance

**Human checkpoints**

| Checkpoint | When |
|---|---|
| Clarification | S1 has blocking questions → human answers, S1 re-runs |
| Design | Always → approve, or reject with feedback (design re-planned) |
| Change-control | Risky change found at S6 (migration, new dependency, large diff) |
| Release | Always → approval pushes the run branch |

**Gates** check real outputs: requirement/design/plan citations, a
technology stack in the design, "a retry must change something", and at S6 the
target's own test suite with coverage ≥ 85%.

**Policies** run on the whole diff at S6. Critical violations stop the run
(writing outside the workspace or allowed paths, touching protected files,
committing to `main`, secrets). Risky changes pause for Change-control
(migrations, new dependencies, large diffs).

---

## 5. Control flow and state

- **Stateless pause/resume.** No long-running process. Each command reloads
  the run's state from disk, drives stages until the next checkpoint or the
  end, saves, and exits.
- **Parallel stages** (S5a/S5b, S7a/S7b) run as two threads. Only the waiting
  on agents is concurrent; commits and event writes go through one lock.
- **Reliability:** bounded retries with feedback, fallback to the human,
  rollback to the last checkpoint, safe-stop (command, time and call limits,
  critical violations), per-call timeout and budget cap.

```
running ⇄ awaiting_approval ─► completed → pushed  |  failed  |  rejected  |  stopped
```

---

## 6. Audit and traceability

- **Run record** per run: state, hash-chained event log, approvals, decisions,
  agent transcripts, config and scenario snapshots, metrics, report.
- **Traceability chain:** frozen requirement → FRs and ACs → design decisions
  → tasks → per-task commits (git trailers) → tagged tests → generated
  `traceability.md`. Any line of code traces back via `git blame` and trailers.
- **Tamper evidence:** each event's hash includes the previous one; edits are
  detectable.
- **Metrics** from events: success, first-pass rate, retries, rollbacks, MTTR,
  latency with and without human wait.

---

## 7. Key decisions

| Decision | Why |
|---|---|
| Custom lightweight engine (not LangGraph) | Fixed graph; one persistence model; no heavy dependency |
| Flat JSON files, TOML config, threads | Simple, inspectable, no new dependencies |
| Agents write files + return a small summary | How Claude Code works; one simple contract (validated in a spike) |
| Post-stage confinement check as enforcement | The spike showed CLI restrictions are not a hard boundary |
| Merge-time CI as the final control | A local tool can't stop its own operator |

---

## 8. Known deviations

Listed in `docs/engineering-summary.md` §8 — notably: requirement documents in
the workspace root rather than `docs/requirements/REQ-…/`; one S6 command gate
instead of five; re-planning only after design rejection; central audit
publishing not built.