# AI Log — Agentic SDLC Orchestrator
Primary tools: Claude chat (design discussion and review), Claude Code (implementation)

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


## 2026-09-29 — T-01: adapt A1 scaffold to the orchestrator project

**Tool:** Claude Code
**Prompt (summary):** Adapt the copied A1 scaffold to this project: remove the
URL-shortener stack, retarget tooling and CI, point CLAUDE.md at
docs/requirements.md as the design source of truth. pyproject.toml was adapted
by me beforehand.

**What the agent did:**
- Removed FastAPI / SQLAlchemy / Alembic / Postgres references from config
  and CLAUDE.md; removed the Postgres service and DATABASE_URL from CI, leaving
  matrix, permissions, pinned actions and timeout unchanged.
- Verified `pip install -e ".[dev]"` in a fresh venv and `scripts/check.py`
  (ruff, ruff format, mypy --strict, pytest + coverage, pip-audit) passing.
- Did not commit, deferring to my definition of done (engineer reviews and
  writes the AI log) — the agent respected a process boundary.

**My verification:**
- Pushed and confirmed CI green on GitHub, not only locally.
- [TODO: if you ran the repo-wide search for leftover references
  (shorten/fastapi/sqlalchemy/alembic/postgres/database_url), note the
  result here; otherwise delete this line.]


## 2026-09-29 — Requirements rev 2

**Tool:** Claude chat, used as a reviewer against the brief; edits applied and
checked by me.
**Trigger:** Re-reading the brief's evaluation criteria ("realism/quality of
outputs", three scenarios each showing decomposition, orchestration and
validation). A mock-only prototype could not satisfy these; the real
`claude -p` executor has to produce the showcase outputs.

**Changes (recorded in the revision history of docs/requirements.md):**
- Showcase runs use the real executor; mock fixtures are derived from those
  runs (D-21, closes O-8). Mock stays for CI, tests and failure injection.
- Per-agent-call timeout added (C9, AC5).
- Central audit-repo publishing moved MUST → SHOULD (time budget); the local
  hash-chained record plus committed evidence keep Phase 1 audit-grade (D-20).
- Submission-level deliverables added to §19 (engineering summary,
  architecture overview, setup and testing approach).
- C11 note mapping rejection-driven re-planning to the brief's "re-plan when
  upstream outputs change".

**Verification:** Checked every changed section against the brief; confirmed
the scope change is reflected consistently across §2, §5.2, C12, §11.1 and D-20.


## 2026-09-29 — Architecture proposal and Phase 1 task list

**Tool:** Claude Code (analysis only; no code, no commands beyond reading files)
**Inputs:** docs/requirements.md (rev 2), docs/assignment.md
**Outputs:** docs/architecture-proposal.md (rev 2), docs/tasks.md
**Review:** done with Claude chat as a second reviewer; I decided which points
to accept and gave all instructions to Claude Code.

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

**Review round 1 — corrections:**
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

**Review round 2 — corrections:**
- Caught a contradiction: the trimmed plan dropped schema change control, but
  the brownfield scenario needs it to trigger change-control approval for its
  migration. Now 7 of 8 policies; only dependency control descoped.
- Added T12 (README, architecture overview, engineering summary), which were
  deliverables missing from the plan.
- Fault injection fixed to one mechanism: the orchestrator writes one failing
  acceptance test before S6 attempt 1, recorded `injected: true`.

**Task list review — corrections before approving:**
- T5.2 made human-owned; brownfield target is a copy of A1 so the submitted
  A1 repo is never modified.
- Added a live `claude -p` smoke call to T4 so executor problems surface
  before the showcase runs.
- Coverage threshold set to 85% (per C15) and made consistent across
  scripts/check.py, pyproject.toml and T9 — my decision to align the gate
  with the documented requirement.

**Verification:** Read both documents in full; checked the gap list, scope
trims and task dependencies against the requirements and the brief.

**Takeaway:** The agent's analysis was thorough on engine mechanics but
optimised for completeness against the requirements rather than for what the
submission is judged on. The key scope decision needed human judgement.


## 2026-09-29 — Hard stop (a): P0 spike and ADR-001

**Built by Claude Code:** ran the `claude -p` spike itself (4 live calls in a
scratch repo, driven via subprocess with timeouts) and drafted ADR-001.

**Spike findings:**
- O-4 verified: agents write files via their tools and return a small JSON
  summary that parses cleanly on the first attempt.
- `--add-dir` gives no real boundary — a live write outside the workspace
  succeeded. `--restricted` stopped it, but it looked like the model refusing
  rather than a hard block. The post-stage file check stays the real
  enforcement.
- `--max-turns` doesn't exist in this CLI version (the suggestion given to the
  agent was wrong); the agent flagged the deviation and used subprocess
  timeout + `--max-budget-usd` instead.

**Review and amendments:**
- Developer and test-engineer agents get Bash limited to running pytest, so
  they can test their own code; other roles get no Bash.
- On timeout, kill the whole process tree (Windows), not just the direct
  child; live timeout test added to T4.1.
- Redacted my local path from the committed spike doc; raw spike results
  committed as evidence.
- Added missing limitations (audit publishing SHOULD; CLI confinement not a
  hard boundary) so the engineering summary includes them.
- I approved ADR-001 before the build started; set Status: Accepted.


## 2026-09-29 — Commit trailer format corrected (during T1)

**Found:** Checked Claude's build commits with
`git log -1 --format="%(trailers)"`. T1.1 and T1.2 showed only
`Co-Authored-By`; the `Task:`/capability trailers were not recognised by git
(not in the final trailer block).

**Why it matters:** The orchestrator's backward trace (C10-AC5) relies on
parseable git trailers. The build history of this repo should meet the same
standard.

**Action:** Instructed Claude to put all trailers in a single final block and
verify with `git log -1 --format="%(trailers)"` after each commit. Did not
rewrite T1.1/T1.2; their subjects start with the task ID, so they remain
traceable.

**Verified:** trailers parse correctly from T2.2 onward (`Task`, `Capability`,
`Co-Authored-By` in one block).

**Also noted:** My own manual commit (3deb5ed) put trailers in the subject
line. Using separate `-m` paragraphs for trailers from now on.


## 2026-09-29 — Hard stop (b): T1–T3 review

**Built by Claude Code (T1.1–T3.2):** domain models, config + validate,
hash-chained event log, mock executor, StageRunner, workspace manager, CLI
(register/validate/run/approve/reject/answer/stop), full S0–S8 graph with
Design and Release checkpoints. 119 tests, ~97% coverage.

**Key proof:** a two-process integration test confirms pause/resume reloads
state from disk (S0 in one process, S1 in a second).

**Agent found and fixed:** the "completed" transition existed in only one of
two code paths; later unified into a single function.

**My verification:**
- Ran scripts/check.py locally. Tests first failed to collect: the package
  wasn't installed in my venv (CI hides this because it installs the
  package). Fixed with `pip install -e ".[dev]"`; asked for a README note so
  graders don't hit the same issue.
- [TODO: manual --mock run — describe what you saw (paused at Design,
  approved from a new terminal, paused at Release, approved, completed;
  approvals visible in approvals.jsonl), or delete this line.]

**Review points raised and fixed (with Claude chat as second reviewer):**
- No task was responsible for the Clarification pause, which the ambiguous
  showcase depends on — now assigned to a named task. Change-control wiring
  made explicit in T6.2 (brownfield depends on it).
- `run` advanced only one stage per call, against the design (drive to the
  next checkpoint); fixed before T4.
- The developer agent's pytest permission pattern didn't match the command it
  would actually run; fixed.
- Claude's manual-test script used `$home`, a read-only PowerShell variable.
- Confirmed the stale-lock recovery tests exist (dead PID, max duration).


## 2026-09-29 — T5.2: target repos prepared (human-owned)

- Created shortener-greenfield-by-agents (empty; only .orchestrator/).
- Created url-shortener-brownfield-target as a copy of A1, with the A1
  remote removed so A1 can never be pushed to. A1 untouched.
- Tagged baseline-greenfield at 976f316 (T-04: shorten, redirect, 404) —
  checked: no analytics or expiry code at that commit.
- Postgres check: A1 uses SQLite locally (Postgres only in CI), so the
  baseline and S6 gates run without a database. scripts/check.py passed
  at the tag.
- Claude Code wrote the .orchestrator/ files; I reviewed the three scenarios
  (reliability text in greenfield, base ref and fault-injection flag in
  brownfield, vague expiry text in ambiguous) and committed/pushed them myself.
- Claude Code asked to read outside its working directory; I added the two
  target repos as working directories instead of allowing reads everywhere.
