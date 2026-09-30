# AI Log — Agentic SDLC Orchestrator
Primary tools: Claude chat (design discussion and review), Claude Code (implementation)

## Summary

**How the work was split**
- **Me, in consultation with Claude chat:** requirements, architecture and
  scope decisions, and review at every stage. Deliberately spent more time up
  front on detailed requirements (~3h) so the build could run with bounded
  agent autonomy and clear acceptance criteria.
- **Claude Code:** analysis, architecture proposal, ADR draft, and the
  implementation, task by task, with tests and per-task commits.
- **Me:** approving at three hard stops, verifying locally, target-repo
  setup (A1 kept untouched), acting as approver in the showcase runs.

**Major decisions (made in consultation with Claude chat)**
- Orchestrator and target projects in separate repos; platform team owns the
  global rules, project teams only supply scenarios and config.
- One fixed stage graph (S0–S8) with entry/exit gates, parallel S5/S7
  branches and four approval checkpoints; agents work inside stages, the
  orchestrator controls everything between them.
- Full traceability: frozen requirement → FRs → design decisions → tasks →
  per-task commits with git trailers → tests; hash-chained event log.
- Design approach (ADR-001): custom lightweight engine, flat JSON files,
  TOML config, threads for parallel stages, stateless pause/resume across
  CLI commands, layer-oriented code layout.
- Agents write files with their own tools and return a small JSON summary;
  workspace confinement enforced by a post-stage check, since the CLI's own
  restriction proved not to be a hard boundary (spike finding).
- Scope: a vertical slice that reaches real runs and all three scenarios,
  rather than a mock-only build; specific items trimmed and listed as
  limitations.

**How oversight worked**
Three hard stops (after the spike and ADR, after the core engine, before the
showcase runs). Each review found real issues — e.g. unwired components,
an unrecoverable fault-injection design, missing per-task commits — which
were fixed before continuing. Details in the entries below.

**Evidence**
docs/requirements.md · docs/architecture-proposal.md · docs/adr/ADR-001 ·
docs/spikes/ · docs/tasks.md · docs/build-notes.md (incl. integration
audit) · evidence/runs/ (showcase runs) · commit trailers
(`git log --format="%(trailers)"`)

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

## 2026-09-30 — Hard stop (c): T4–T9 review, integration audit, pre-T10 fixes

**Built by Claude Code (T4–T9):** real executor + 7 agent profiles (live smoke
and timeout tests passed), greenfield template, parallel S5/S7 join, policies,
retries/rollback/safe-stop, design-rejection re-planning, clarification
checkpoint, fault injection, traceability, metrics/report/PR description.

**Claude Code findings:**
- claude -p silently refuses writes under OS temp paths — workspaces must
  live in normal directories.
- Reaching COMPLETED/REJECTED emitted no event, so run success couldn't be
  computed from events alone; added a RUN_TERMINAL event.
- Flagged (without guessing) that the CLI still refused the real executor —
  built and tested in T4 but never wired into run/approve/reject/answer.

**Decision (reviewed in collaboration with Claude chat):** showcase runs go
through the CLI, not a script calling the executor directly — a script would
bypass approvals, policies and the event log, and graders can only reproduce
the CLI.

**Integration audit** (requested because a tested component had never been
wired in): found S0/S6/S8 were stubs (S6 would have passed without running
tests or coverage), profiles lacked the citation format the traceability
gates expect, and run.json, push after release, workspace venv, the rollback
command and the artifact writes were unwired. All fixed; added an end-to-end
CLI test asserting every run artifact is produced.

**Review of the audit's "not fixed" list (done in collaboration with Claude
chat) — sent back before T10:**
- S5a made one call and one commit for all tasks, so no per-task commits
  and no working backward trace — core to the traceability design (D-8).
  Now one call and one commit per plan task, with trailers.
- Greenfield ran S2 despite §12 requiring it to be skipped. Now skipped with
  a recorded reason.
- With S6 now real, the injected fault could never be fixed (the developer
  agent can't write to tests/acceptance/), so the brownfield retry demo would
  end as failed. Changed to a defect in src/ that the fix call can repair;
  still recorded as injected: true.
- Accepted as documented limitations: flat file layout instead of
  docs/requirements/REQ-…/, a single S6 gate running all checks via
  check.py, run branches pushed to the local target clone (pushed to GitHub
  manually), and a small lock gap between resolve and drive.

**Boundary overstep:** while verifying the fixes, Claude Code ran a full mock
run against the real greenfield target repo and pushed a branch into it (then
deleted it) without asking — the target repos are human-owned. It disclosed
this itself. Repo verified clean; Claude Code instructed to use throwaway
repos for any further verification.

**Result:** 283 tests, full gate green. Ready for T10.1.

## 2026-09-30 — Fixes after the first real run

Claude Code fixed all findings from run 001 (325 tests, 96.23% coverage).

**Root cause of the unchanged design (diagnosed by Claude Code):** the
design-rejection path re-ran S3 but never saved the rejection comment where
the prompt builder could read it (the clarification path did), so S3 got an
identical prompt and produced an identical design. Combined with a retry
budget counted cumulatively rather than per re-plan, the single failure
ended the run. Fixed both; added a gate that fails any retry which changes
nothing.

**Other fixes:** citation gates parse real headings and fail on zero items;
agent transcripts and agent_call_id recorded; run record now includes
scenario and config snapshots and stage artifacts; architect must state a
technology stack (profile rule + new gate).

**Metrics check against run 001's real data:** confirmed and fixed two
counting bugs — a skipped stage counted as a first-pass failure (explained
the 0.5), and automatic retries emitting no retry event. Design rejections
are intentionally counted in retry_count (documented in the README).
