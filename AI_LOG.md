# AI Log — Agentic SDLC Orchestrator
Primary tools: Claude chat (design discussion), Claude Code (implementation)

## Setup — Repo scaffold
- Copied T-01 scaffold files from assignment 1 and committed them unmodified
  ("Copy scaffold from assignment 1 (unmodified)") so the later adaptation is a
  clean, reviewable diff.

## docs/requirements.md — Orchestrator requirements
Tool: Claude chat (design discussion over several iterations)
How it was produced: I drove the design through questions and corrections;
Claude chat proposed structures and options and drafted the document; I reviewed
each version and requested changes. Final version reviewed by me.

### Decisions driven by me
- Orchestrator in its own repo named for what it is (agentic-sdlc-orchestrator),
  separate from the URL shortener; project ID = target repo name
- Runs grouped by project; target project named explicitly in every requirement
- Platform team owns and maintains the orchestrator and all global rules;
  project teams only use it (corrected an ownership wording in the draft)
- Global rules (stage graph, entry/exit gates, approvals) defined once at
  orchestrator level; engineers must not be able to weaken them locally
- Run records must be stored centrally and published automatically, not left
  on the engineer's machine
- Original requirement must never be edited; full traceability
  requirement → FRs → design → tasks → commits, with commits traceable to tasks
- S2 codebase analysis for every existing codebase; S3 creates architecture for
  greenfield and updates it for significant changes; S4 maps tasks under each FR
- Agent profile/persona per role (analyst, architect, planner, developer,
  test engineer, technical writer, reviewer)
- Test exit criteria: all tests pass and coverage >= 85%
- Engineer raises the PR and the approver merges; nothing committed to main
- Build only MUST items first; project-level hardening moved to COULD

### AI proposals I accepted (with my reason)
- Workspace (agents write) vs run record (orchestrator only) — agents can't
  alter their own audit trail
- Approved greenfield template — quality gates exist from the first stage
- Approved-dependency list per project — governs new deps without approving
  routine ones every run
- Merge-time CI on GitHub as the authoritative control, plus tamper evidence
  (orchestrator version + config hash, hash-chained events) — honest answer to
  "a local tool can't stop its operator"
- Project config in the target repo's .orchestrator/, read from main
- failed (work unacceptable) vs stopped (safety/control halt)
- Code + unit tests in S5a, acceptance tests from ACs in S5b, in parallel
- Per-task commits with git trailers (Task, FR, Req, Run, Stage)
- Coverage threshold enforced by the orchestrator itself, not the target's config
- Mock executor — required anyway for tests/CI; lets reviewers run without Claude
- Central audit repo published at every approval pause and at run end

### Gaps found in review and fixed
- Parallel agents writing the same workspace → path partitioning per stage
- S7b high-severity findings had no defined path → loop back to S5a (bounded)
- S7a docs ran after verification → restricted to documentation paths
- Draft said design would be "too big for a day" → explicit Phase 1 / Phase 2 /
  COULD build scope

### Open (for the architecture proposal)
Graph engine (LangGraph vs custom), state storage, config format, agent output
contract, parallel execution, workspace confinement for claude -p, policy
expression, mock fixtures, module layout, applying profiles to claude -p.

Duration: 3 hours


## 2026-09-29 — Architecture proposal and Phase 1 task list

**Tool:** Claude Code (analysis only; no code, no commands beyond reading files)
**Inputs:** docs/requirements.md (rev 2), docs/assignment.md
**Outputs:** docs/architecture-proposal.md (rev 2), docs/tasks.md

**Prompt (summary):** Analyse the requirements for gaps and brief coverage;
decide open items O-1..O-10 with options, trade-offs and a Verified/Assumed
status; propose architecture and module layout; produce an ordered build plan
traced to capability/AC IDs with effort and scope risks for ~12h.

**What the agent identified on its own:**
- The need to validate `claude -p` behaviour before building the real executor
  (P0 spike), without being told; O-4, O-6 and O-10 marked "Assumed".
- 12 gaps (G-1..G-12), notably: pause/resume must rebuild state from disk
  across CLI processes; stale-lock recovery; git and event-log races between
  parallel stages (fixed with a single lock and path-scoped `git add`);
  protected paths vs. dependency control in the same file; fixture fallback
  for tests before any real run exists.
- B-1: the brief asks for "reliability features", but none of the three
  scenarios requested any.

**Review round 1 — my corrections:**
- Scope: the agent's plan concluded 12h reaches only a mock-only build, with
  the real executor and all showcase runs deferred. Rejected: the brief grades
  realism of outputs and the three scenarios. Revised D-19 so the build is a
  vertical slice reaching real runs, with specific MUST items trimmed and
  recorded as limitations.
- Added gaps it missed: G-13 (S6 retry = one fix call, `Stage: S5a-fix`
  trailer), G-14 (rollback target = checkpoint recorded at every passed stage),
  G-15 (review loop also invalidates S7a docs), G-16 (honest fault injection
  for the brownfield retry demo).
- O-4: replaced "return documents as text with fenced JSON" with "agents write
  files via tools, return a small JSON summary; gates read the files".
- Accepted B-1: greenfield requirement text broadened to include reliability
  behaviour.

**Review round 2 — my corrections:**
- Caught a contradiction: the trimmed plan dropped schema change control, but
  the brownfield scenario needs it to trigger change-control approval for its
  migration. Now 7 of 8 policies; only dependency control descoped.
- Added T12 (README, architecture overview, engineering summary), which were
  deliverables missing from the plan.
- Fault injection fixed to one mechanism: the orchestrator writes one failing
  acceptance test before S6 attempt 1, recorded `injected: true`.

**Task list review — my corrections before approving:**
- T5.2 made human-owned; brownfield target is a copy of A1 so the submitted
  A1 repo is never modified.
- Added a live `claude -p` smoke call to T4 so executor problems surface
  before the showcase runs.
- Coverage threshold aligned between check.py and the task list (<value>).

**Verification:** Read both documents in full; checked the gap list, scope
trims and task dependencies against the requirements and the brief.

**Takeaway:** The agent's analysis was thorough on engine mechanics but
optimised for completeness against the requirements rather than for what the
submission is judged on. The key scope decision needed human judgement.

## 2026-09-29 — ADR proposal

I approved ADR-001 before the build started