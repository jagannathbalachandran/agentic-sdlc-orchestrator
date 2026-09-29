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