# Architecture proposal — Agentic SDLC Orchestrator

Input: `docs/requirements.md` (rev 2) and `docs/assignment.md`. This is an analysis and
design document only — no code, no ADRs. For review before any ADR or implementation work
starts.

> **Rev 2 (2026-09-29)** — incorporates reviewer decisions: D-19 revised (§4 scope), four
> new gaps (G-13–G-16), O-4 revised (tool-based artifact writes, not fenced-JSON-in-result),
> B-1 accepted, and the build plan re-estimated as a ~12–13h vertical slice that reaches the
> real executor and all three showcase runs.

---

## 1. Requirements analysis

### 1.1 Gaps, ambiguities and contradictions

Each item: why it matters, then a proposed resolution. IDs are referenced later in
§2–§4 so decisions and tasks can point back to the gap they close.

**G-1. Pause/resume crosses a process boundary, and nothing in the doc says how.**
C7-AC1 says a run "pauses with state persisted; `approve`/`reject`/`answer` in a later
command resumes it." Every CLI invocation is a separate OS process — there is no
long-running orchestrator process to "resume." If this isn't nailed down early, the
engine can accidentally grow in-memory state that silently breaks on the very first
`approve` call in a different process.
*Resolution:* treat every checkpoint as a full process exit; `run`, `approve`, `reject`,
`answer` all re-enter one shared driver function that rebuilds all state from
`run.json`/`graph.json` on disk. See §3.2.1.

**G-2. Run-lock recovery after a crash is unspecified.**
D-18 mandates one active run per project via a lock, but "resume after process kill" is
explicitly Phase 2 (SHOULD, C9-AC4). That leaves a hole: if the orchestrator process dies
mid-stage in Phase 1, what releases the lock? Nothing in the doc says.
*Resolution:* lock file records PID + acquisition time; a later `run`/`stop` on the same
project detects a dead PID or an age past `max_run_duration` and force-clears it with a
clearly reported reason. This does **not** require building mid-stage resume — it only
prevents a dead process from permanently blocking the project. See §3.2.1.

**G-3. Git commits and the event log are not protected from the parallel stages that
write through them.**
§7.3 partitions *files* between S5a/S5b and S7a/S7b so their edits never collide, but
`git commit` and the hash-chained `events.jsonl` (D-7) are each a single mutable
resource (HEAD, index, previous-hash pointer) shared by both branches. Two threads
committing or appending an event at the same instant can race even though their files
never overlap. Nothing in the doc addresses this.
*Resolution:* the concurrency is confined to *waiting on the external agent call*; every
side effect the orchestrator performs in response (git add/commit, event append,
run-record update) is serialized through a single in-process lock per run. See §3.2.2.

**G-4. "Protected paths" is file-level, but the dependency-control policy needs
section-level access to the same file.**
C6 lists `pyproject.toml`-adjacent things only implicitly, via "quality config" as a
protected path, while the dependency-control policy must let S5a add an *approved*
dependency to `[project.dependencies]` in that same file. A whole-file protection rule
and a policy that must edit part of that file are in tension.
*Resolution:* protect specific TOML tables (`[tool.ruff]`, `[tool.mypy]`,
`[tool.pytest.ini_options]`, `[tool.coverage.*]`, `[build-system]`), not the whole file;
`[project.dependencies]` is checked by the dependency-control policy instead of being
blanket-protected. Section-aware diffing, not path-only diffing.

**G-5. "Quality config" and "secrets files" (C6, protected paths) are undefined terms.**
Neither has a concrete filename or glob. Without one, the protected-paths policy can't
be implemented or tested (C6-AC1 requires a test proving detection).
*Resolution:* "quality config" = the TOML tables in G-4 plus `scripts/check.py`
(already named separately); "secrets files" = `.env*` except `.env.example`, and any
path matching common credential filenames (`*.pem`, `id_rsa*`, `*.key`). Also make
protected-path globs match historical requirement folders
(`docs/requirements/*/00-source.md`), not only the current run's — the doc's own wording
("00-source.md is protected") reads as singular but every prior REQ's baseline needs the
same protection from later runs.

**G-6. No numeric defaults for the limits the reliability controls depend on.**
C6's diff-size limit, and C9's max run duration, max agent calls, and per-agent-call
timeout, are all named as controls but none has a default value in the doc. Risk §18
("runaway time/cost") is mitigated by exactly these numbers, so shipping without
defaults leaves the named mitigation unimplemented.
*Resolution:* set conservative Phase 1 defaults in `config/defaults.toml`: diff-size
limit 400 changed lines or 15 files; per-agent-call timeout 10 minutes; max agent calls
per run 60; max run duration 3 hours (wall clock, excluding time spent awaiting
approval). All overridable only by project *hardening* (COULD), never loosened.

**G-7. Secret-scan implementation is unspecified, and the obvious implementations
conflict with "no new deps without approval."**
C6 names "pattern scan of every stage diff" as a MUST policy but doesn't say whether
that's a hand-rolled regex list or a third-party scanner (e.g. `detect-secrets`,
`gitleaks`). The current `pyproject.toml` has no such dependency.
*Resolution:* implement an in-house regex set for the common high-confidence patterns
(AWS access keys, generic `api[_-]?key`/`secret` assignments, PEM private-key blocks,
bearer tokens) as a Phase 1 policy with zero new dependencies. Document explicitly as a
narrower net than a dedicated scanner — this is a stated limitation, not silently
assumed thoroughness.

**G-8. Mock-executor fixture lookup has no defined fallback for scenarios that were
never run for real.**
D-21/O-8 settle that fixtures are derived from the three showcase runs, but C15-AC1
requires the orchestrator's *own* test suite to run entirely on the mock executor — and
those tests need stage responses for scenarios that will never have a showcase run
behind them. Likewise a reviewer inventing a fourth scenario and running `--mock` has
nothing to replay.
*Resolution:* two-tier mock executor — exact fixture replay keyed by
`(scenario_id, stage_id, attempt)` for the three showcase scenarios, falling back to a
small bundled set of generic synthetic stage responses (clearly documented as
non-scenario-accurate) used by the orchestrator's own unit tests and by any
unrecognized scenario. Detail carried into §2, O-8.

**G-9. Re-planning is defined only for Design (S3) rejection; Change-control and Release
rejection are not.**
C11 and its AC1 describe exactly one re-planning trigger: rejecting the design re-runs
S3 onward. The rev-2 changelog claims "C11 note mapping rejection-driven re-planning to
upstream-change re-planning," but the body never extends this to a rejected
Change-control approval (occurs mid-S6, over a risky diff already produced by S5a) or a
rejected Release approval (occurs at S8, over the finished, gated result). Whether a
plain `reject` (non-`--final`) at these two checkpoints re-plans, and *what* it
re-plans, is not stated.
*Resolution:* Change-control rejection with feedback re-runs S5a for the flagged
change only (same bounded-retry mechanism S6 gate-failures already use, §7 diagram),
then S6 again — it is not a new design, so S3/S4 stay valid. Release rejection with
feedback is treated as a Change-control-style loop back to S5a as well, since nothing
new is produced at S8 to revise; there is no "S8 redesign" to re-run. `--final` at
either checkpoint still ends the run as `rejected` with no re-planning, matching D-14.

**G-10. Whether a Clarification checkpoint can be rejected, not just answered, is
unstated.**
C1 gives `answer` as a separate command from `approve`/`reject`, implying Clarification
resolves only via `answer`. But nothing says what a human does if a blocking question
can't be answered and the run should simply stop.
*Resolution:* `orchestrator stop <run-id>` remains the correct way to end a run stuck at
Clarification — no new command needed. Document this explicitly so it isn't rediscovered
as a missing feature later.

**G-11. Runtime location of shipped data relative to an installed package is not
addressed.**
§8 places `config/defaults.*`, `agents/profiles/`, `templates/`, `fixtures/mock/` at the
orchestrator repo root, outside `src/orchestrator/`. §5.1 describes the prototype as "a
clone [of the orchestrator repo]... used unmodified," not a `pip`-published package used
from an arbitrary working directory — so for Phase 1, resolving these paths relative to
a discovered repo root (walk up from `__file__` to find the marker files) is sufficient;
packaging them as installed package data (`importlib.resources`) is unnecessary now.
*Resolution:* documented as a Phase 1 assumption in §3.1; flagged as a production-path
(COULD) concern only if/when the orchestrator is distributed as a standalone package.

**G-12. "Code baseline" (base ref → commit ID) doesn't have a defined meaning for
greenfield runs.**
§7.2 defines the code baseline as "the exact commit the run started from," which
presumes a pre-existing base ref. C3-AC2 says greenfield instead does `git init` plus a
setup commit — there is no incoming base ref to record.
*Resolution:* for greenfield, the code baseline **is** the setup commit created in S0
(the first commit of the new repo); `run.json`'s `base_ref`/`base_commit` fields record
that commit's SHA with `base_ref = null` (no tag/branch existed before the run).

**G-13. S6→S5a retry loop doesn't say how many agent calls happen, or how the resulting
commit is distinguished from a normal task commit.**
§7's diagram says a failed S6 gate goes "back to S5a with the failure output (max 3)," but
not whether that means re-running the whole S5a task loop or a single targeted fix, and
C10-AC2 requires every S5a commit to carry exact `Task`/`FR`/`Req`/`Run`/`Stage` trailers —
a fix commit needs its own convention so it isn't misread as original implementation work.
*Resolution (reviewer-decided):* exactly **one fix call per retry attempt**, scoped to the
gate's failure output, not a re-run of the full task loop. Its commit trailer reads
`Stage: S5a-fix` (not `S5a`), plus the `Task`/`FR` it targeted — so `traceability.md` and
`git blame` can tell an original implementation commit from a retry fix at a glance.

**G-14. "Roll back to the last good commit" is ambiguous when the most recently passed
stage didn't itself commit anything.**
C9's rollback control targets "the last good commit," but §7's stage table shows several
stages commit 0 times (S2, S6, S7b, Join S5) — so after one of those passes, "the last
commit" is stale, not "good" in the sense of "reflects everything that has passed so far."
*Resolution:* record an explicit **checkpoint** — the current `HEAD` SHA — every time a
stage's exit gate passes, whether or not that stage itself committed. Rollback always
resets to the most recently recorded checkpoint, never to "whichever stage happened to
commit last."

**G-15. The S7b→S5a review-findings loop doesn't say which already-completed downstream
stages become stale.**
§7's diagram shows "high-severity finding → back to S5a with findings (max 2) → S6 again,"
but S7a (docs) has already run once by this point, and a fix driven by review findings can
change the API surface S7a's output describes — nothing says S7a's prior output should be
treated as invalidated.
*Resolution:* the S7b→S5a loop invalidates **S6, S7a and S7b** — all three re-run after the
fix, matching C11-AC2's existing principle (downstream stages are marked `invalidated`
whenever an earlier stage's output changes) applied to this bounded loop rather than only
to design rejection.

**G-16. Nothing addresses how the brownfield showcase reliably demonstrates "retry after a
gate failure" (§12) with a real agent that might just get it right first try.**
A real `claude -p` call has no guaranteed failure mode to demonstrate the S6→S5a retry loop
on demand, and silently forcing a failure without recording that it was forced would
undermine the audit trail's honesty.
*Resolution (reviewer-decided):* when the brownfield scenario flags fault injection, the
**orchestrator itself** — not an agent — writes one failing acceptance test into
`tests/acceptance/` immediately before S6's first attempt for that run, deterministically
forcing exactly that one S6 failure and triggering the S6→S5a retry loop (G-13). The event
this produces is recorded with `injected: true` in `events.jsonl`, and the write is
attributed to the orchestrator (not S5b/the reviewer agent), so the audit trail stays
honest about what was staged for the demonstration versus what happened organically.

### 1.2 Brief requirements not covered by `requirements.md`

**B-1. "Reliability features" (assignment §2) never appears as a requirement in any of
the three demonstration scenarios.**
The brief's scenario description is "core APIs, analytics, **and reliability
features**." Of the three scenarios in requirements §12, the greenfield REQ text is
"Shorten, redirect, 404 for unknown codes" (APIs only), the brownfield REQ is "Add click
analytics" (analytics only), and the ambiguous REQ is "Links should expire." None asks
for anything a reader would call a *reliability* feature (e.g. input validation on
malformed URLs, rate limiting, idempotent redirect handling, graceful handling of
storage failures). Since the orchestrator's S1 derives FRs strictly from the REQ text
given, reliability requirements will never surface in any run unless the REQ text asks
for them — meaning this brief requirement risks going entirely undemonstrated.
*Accepted (reviewer decision).* The greenfield scenario's REQ text is broadened to
explicitly include basic reliability behavior: reject malformed input with a clear error,
handle an unknown short code as 404 rather than a crash, avoid collisions on generated
codes. S1 then derives ACs that cover it naturally — no fourth scenario needed, just a
fuller REQ for the one that already runs the full graph. This is the REQ text authored
into `.orchestrator/scenarios/*.toml` as part of target repo prep (§4.1).

**B-2. "Scalable code" (assignment §6, evaluation criteria) isn't addressed for the
target product.**
The requirements document is thorough about the *orchestrator's* own quality bar
(C15: ruff, mypy strict, coverage, pip-audit) but says nothing about what "scalable"
should mean for the URL shortener the orchestrator produces (e.g. is an in-memory store
acceptable for the prototype, or must S3's design decisions justify a storage choice
against expected load?). Lower-severity than B-1 — likely acceptable to leave to each
run's S3 design-decision rationale rather than a fixed global requirement — but worth
naming as a deliberate omission rather than an oversight.

---

## 2. Decisions on §17 open items (O-1–O-10)

Each item: options, trade-offs, recommendation, and a status of **Verified** (grounded
in something already confirmed by reading the requirements/assignment or established
language/stdlib facts) or **Assumed** (depends on behavior — usually `claude -p`'s
actual CLI surface — not yet exercised in this session), with how/when to validate.

### O-1. Graph execution engine: LangGraph vs. custom lightweight engine

**Options**
- *LangGraph*: mature graph runtime with built-in checkpointing and human-in-the-loop
  interrupts.
- *Custom lightweight engine*: a static list of `StageSpec`s (the graph is fixed and
  global per §7, not constructed per run) driven by a small finite-state machine, with
  all persistence going through the flat files §11 already mandates.

**Trade-offs.** LangGraph's checkpointing is built for its own state model, which would
have to be reconciled with the hash-chained `events.jsonl`/`run.json`/`graph.json`
format §11 already fixes as DECIDED — effectively building the same persistence twice.
It also adds a heavy, fast-moving dependency (langgraph + langchain-core) to a package
that currently depends on nothing but pydantic, working against CLAUDE.md's
approval-required new-dependency rule and NFR §13's "engine independent of ... storage."
A custom engine is more code up front but every piece of state it needs to persist is
already required output, so there's no second persistence model to keep in sync.

**Recommendation:** custom lightweight engine — a static graph of `StageSpec`s plus a
run-level FSM, described in §3.2.

**Status: Assumed.** The requirements facts behind this (fixed graph, mandated flat-file
outputs, executor/storage independence NFR) are verified from the doc. The engineering
claim "custom is simpler here" is judgment, not something tested this session.
*Validate:* build the S0→S1 walking skeleton with pause/resume (build-plan T3, "engine
walking skeleton") early; if the FSM/resume design proves inadequate for the parallel
joins or approval re-entry, that's the point to reconsider, before more stages are built
on top of it.

### O-2. State storage: JSON/JSONL files vs. SQLite

§11 already fixes the *run record's* file formats as DECIDED, so this item is really
about whether an additional SQLite layer sits underneath — a queryable cache for
`runs list`/`status`/lock state — or whether flat files are the only storage,
everywhere.

**Options**
- *Pure flat files*: `index.jsonl` scanned for `runs list`; `graph.json` re-parsed for
  status; a PID+timestamp lock file for the one-run-per-project constraint.
- *SQLite as a derived cache*: flat files stay authoritative per §11; SQLite (stdlib
  `sqlite3`, no new dependency) accelerates queries and gives transactional locking.

**Trade-offs.** SQLite adds real value once querying dozens+ runs with filters matters,
and gives atomic locking for free. At prototype scale (one engineer, a handful of runs
per demo) that value is small, and a derived cache is one more thing that can drift from
the files that are the actual source of truth per §11.

**Recommendation:** pure flat files. Atomic writes (write-temp, `os.replace`) for
`run.json`/`graph.json` updates; a PID+timestamp lock file (G-2) for locking.

**Status: Assumed** (scale is small enough that SQLite's benefits don't pay for
themselves; not measured). *Validate:* keep the index/lock access behind a small
repository-style interface so SQLite could replace it later without touching engine
code; only revisit if `runs list` needs to scale past what directory scanning
comfortably handles.

### O-3. Config format: TOML (`tomllib`) vs. YAML (PyYAML)

**Options**
- *TOML via stdlib `tomllib`*: read-only in the standard library (Python 3.11+, matching
  the NFR); would need a TOML *writer* for the one machine-written artifact,
  `config.effective.*`.
- *YAML via PyYAML*: reads and writes easily, but is an external dependency not
  currently in `pyproject.toml` (needs explicit approval + a version bound per
  CLAUDE.md), and its richer grammar (anchors, tags) is a small extra surface for
  something that ingests project-authored config.

**Recommendation:** TOML (`tomllib`) for every human-authored file
(`config/defaults.toml`, `.orchestrator/project.toml`, `.orchestrator/scenarios/*.toml`)
— zero new dependency, and it already matches this repo's own `pyproject.toml`
convention. For the one machine-written artifact, use **JSON** instead of TOML
(`config.effective.json`) rather than adding a TOML writer — it's a machine snapshot,
not something anyone hand-edits, so TOML's human-friendliness doesn't apply to it. No
new dependency needed anywhere.

**Status: Verified.** `tomllib` is stdlib from Python 3.11 (matches §13's floor);
PyYAML is confirmed absent from the current `pyproject.toml`. The recommendation follows
directly from those two facts, not from unconfirmed behavior.

### O-4. Agent output contract: `claude -p` JSON output + pydantic vs. fenced JSON

**Revised (reviewer decision) — settled, not a trade-off between the two original
options.** Every stage's agent writes its deliverable files directly into the workspace
using its own tools (Write/Edit/Bash), exactly where the `StageSpec` says they belong —
this is how Claude Code naturally operates (a tool-using coding agent, not a
document-completion API), so the profile just has to ask for what the agent already
does by default. The call's *response* carries only a small JSON summary: the IDs it
produced (e.g. `FR-8`, `FR-9`) and the list of files it wrote or touched. Gates then read
the actual files off disk — `01-requirements.md`, `src/...`, `tests/...` — not anything
parsed out of the response text. The previously-considered fenced-JSON-in-result approach
(extracting a trailing ` ```json ` metadata block from the response, per the earlier
draft of this section) is dropped.

**Why this is better than either original option.** Asking the model to emit its entire
deliverable as response text (bare or fenced) fights its normal mode of operating and
demands a strict, easy-to-violate response-format contract — exactly the source of this
item's earlier "Assumed" risk. Trusting only a small, narrow JSON summary shape is a much
easier contract to hold the model to, and the actual deliverable is validated from the
same source of truth a human reviewer or `git diff` would use: the files themselves.

**Consequence for the mock executor (O-8):** since gates read files, not response text, a
mock replay must also materialize the fixture's file contents into the workspace, not just
return a canned summary — otherwise a mock run and a real run would be checked against
different sources of truth. Folded into O-8 below.

**Consequence for §3.3:** `AgentCallResponse` = `{summary, produced_ids, files_written}`,
not a payload to parse; `Gate` implementations read from the workspace filesystem.

**Status: Verified** (P0 spike, `docs/spikes/claude-p-feasibility.md`). A live
`claude -p` call wrote its deliverable file exactly where instructed via its own
tools and returned the requested summary shape (`{produced_ids, files_written}`)
verbatim, first attempt, no fences or extra text to strip. No further validation
needed before T4.1.

### O-5. Parallel execution: threads vs. asyncio vs. subprocess pool

Only S5(a/b) and S7(a/b) ever run two agent calls at once; each call is a blocking
`claude -p` subprocess that mostly waits.

**Options**
- *Threads* (`ThreadPoolExecutor`, or just two `threading.Thread`s joined at the sync
  point): `subprocess.run` releases the GIL while waiting, so two blocking subprocess
  calls overlap naturally.
- *asyncio*: would require the otherwise-synchronous CLI/engine to become async-aware or
  bridged, for a fixed concurrency of exactly two.
- *Subprocess pool*: adds nothing — each unit of work (`claude -p`) is already its own
  OS process; a multiprocessing pool would add pickling/IPC overhead for no benefit,
  since there's no CPU-bound Python work being parallelized.

**Recommendation:** threads. Two `Thread` objects per join point, `.join()`ed before the
gate evaluates — no general pool abstraction is needed for a fixed fan-out of two.

**Status: Verified** for the concurrency-primitive choice (subprocess + GIL-release
behavior is a settled Python guarantee). **Assumed** for the part that actually matters
— safe interaction with the shared git working tree and event log while two threads run
— addressed as a design in §3.2.2 and closing G-3, not yet exercised against a real git
repo. *Validate:* an integration test that runs two mock-executor branches concurrently
against a throwaway git repo and confirms both file sets and both commits land cleanly.

### O-6. Workspace confinement for `claude -p`: tool/dir restrictions vs. post-stage
checks vs. both

C6 already names the policy "Workspace confinement — **post-stage check**," so the
post-stage check is not actually open — it's DECIDED. What's open is whether a
preventive layer (Claude Code's own directory/tool restriction) is added on top.

**Options**
- *Post-stage check only*: snapshot the workspace before the call, diff after; catches
  every escape regardless of mechanism, but only after the fact.
- *Both*: add directory/tool restriction at call time (first line of defense) plus the
  mandated post-stage check (the check that actually decides pass/fail, per §5.2's
  layered-control framing for this exact threat).

**Recommendation:** both. The post-stage diff+hash check is the non-negotiable
enforcement point (cheap, since the workspace is disposable and already fully
controlled); a preventive layer reduces how often that check has to catch something,
avoiding a wasted retry/rollback cycle for a confinement failure that could have been
prevented instead of just detected.

**Status: Refined, still partially Assumed** (P0 spike,
`docs/spikes/claude-p-feasibility.md`). `--add-dir` alone gives **no** real
boundary — a live test wrote to an absolute path outside it without any denial.
`--restricted --add-dir <workspace> --allowedTools <list>` did block the same write,
but the observed refusal looked like model judgment (declined in text, before
attempting the tool call; `permission_denials` stayed empty), not an observed hard
technical denial — one sample, not proof of a guaranteed block. Recommendation
updated to use `--restricted`, not bare `--add-dir`, as the preventive layer; the
mandatory post-stage diff+hash check (C6, DECIDED) remains the actual enforcement
point, unchanged, exactly as this section originally anticipated.

### O-7. Policy expression: Python classes vs. declarative rules

**Options**
- *Python classes* implementing a common `check(context) -> PolicyResult` interface, one
  per C6 policy.
- *Declarative rules*: globs/regexes/thresholds interpreted by one generic engine.

**Trade-offs.** Some C6 policies are purely data-shaped (protected paths = globs,
diff-size limit = a number, secret scan = a regex list) — a natural fit for declarative
config, and exactly the shape §9's project-hardening layer needs to mechanically verify
"only ever tightens." Others are inherently procedural (workspace confinement diffs a
filesystem snapshot; dependency control parses `pyproject.toml` and diffs against an
approved list from a different file) and can't be expressed as rules alone.

**Recommendation:** Python classes, uniformly — but each class reads its *parameters*
(globs, thresholds, regex lists) from the layered config rather than hardcoding them, so
the declarative values §9 needs to compare across layers still live in
`config/defaults.toml`, while the evaluation logic stays one consistent, independently
testable shape (closing the loop with C6-AC1).

**Status: Verified** — follows directly from re-reading C6's actual policy list (mixed
structural/procedural) and §9's tightening-only requirement; no unconfirmed runtime
behavior involved.

### O-8. Mock fixtures: format, redaction, and lookup (remaining detail after D-21)

D-21 already decides fixtures are derived from the three real showcase runs. Left open:
format, redaction, and — closing G-8 — what a non-showcase scenario does.

**Format (revised for O-4's tool-based-write approach):**
`fixtures/mock/<scenario>/<stage>[-<attempt>].json`, storing the small JSON summary
(`produced_ids`, `files_written`) **plus a `files` map of relative path → content**
captured from what the showcase run actually wrote into the workspace. On replay, the
mock executor materializes those files into the run's workspace before returning the
summary — the same thing a real call would have left on disk — so gates read the same
kind of on-disk artifact regardless of executor, closing the gap O-4's revision would
otherwise leave (gates read files; a mock that only replayed the summary would starve
them).

**Redaction:** target repos hold no real secrets (per the "no credentials stored" NFR),
but transcripts can still carry incidental local detail (absolute Windows paths under
the engineer's username, hostnames). Before committing to `fixtures/mock/` or
`evidence/runs/`: strip absolute local paths to a placeholder, strip hostnames, and run
the orchestrator's own secret-scan policy (G-7) over the fixture files before commit —
dogfooding the same check applied to target diffs.

**Lookup for non-showcase scenarios (closes G-8):** key fixture lookup by
`(scenario_id, stage_id, attempt)`; if `scenario_id` has no fixture directory, fall back
to a small bundled set of generic synthetic responses used only by the orchestrator's
own unit tests and by a reviewer experimenting with an invented scenario — explicitly
labeled non-scenario-accurate, decoupled from the showcase fixtures so regenerating one
doesn't break the other.

**Status: Assumed.** No real showcase run has happened yet in this session, so the exact
shape of `claude -p`'s output and what incidental data shows up in transcripts is
unconfirmed. *Validate:* during the first real-executor showcase run (greenfield),
inspect the actual transcripts for anything needing redaction and finalize the fixture
schema then, before deriving fixtures for the other two scenarios.

### O-9. Module layout of `src/orchestrator/`

**Options**
- *Layer-oriented*: subpackages by architectural role (`engine/`, `gates/`, `policies/`,
  `executors/`, `models/`, `cli/`, `audit/`, ...).
- *Stage-oriented*: subpackages by SDLC stage (`s0_prepare/`, `s1_requirements/`, ...),
  each colocated with its own gate/policy code.

**Trade-offs.** All nine stages share identical gate/policy/event-emission plumbing —
they differ only in which agent profile, prompt, and output schema is used. A
stage-oriented layout would fragment that shared plumbing across nine near-duplicate
packages; a layer-oriented layout keeps it in one place, tested once, generically. This
also matches CLAUDE.md's core-engine/executor-independence rule directly: executor code
needs to be its own package boundary regardless of how stages are organized.

**Recommendation:** layer-oriented, with each of the nine stages represented as a small
declarative `StageSpec` (not a package) rather than nine stage packages. Full layout in
§3.1.

**Status: Verified** — grounded directly in NFR §13 and CLAUDE.md's executor-boundary
rule, both already read in full.

### O-10. Applying profiles to `claude -p`: rendered system prompt + flags vs. Claude
Code subagent/skill files

**Options**
- *Rendered system prompt + flags*: the orchestrator renders each profile (persona,
  responsibilities, tool allowlist, output contract, input context) into a prompt string
  at call time and passes it via CLI flags on a one-shot `claude -p` invocation — no
  persistent Claude Code project config involved.
- *Claude Code subagent/skill files*: define each role as a `.claude/agents/*.md`
  subagent and have `claude -p` delegate to it, relying on Claude Code's own
  tool-scoping per subagent.

**Trade-offs.** Subagent files could give tool-scoping "for free," but they couple the
profile system to Claude Code's specific file format/location and require writing
orchestrator-managed files into (or near) the workspace before every call — files that
would then need special-casing in the workspace-confinement/protected-path reasoning
since they're not target-repo content. They also make the "profile version hash" story
murkier, since Claude Code's own prompt assembly for a subagent is partly opaque to the
orchestrator. Rendered prompt + flags keeps the orchestrator in full control of exactly
what text the model receives, which is also what makes O-8's fixture replay simple: a
fixture is just (rendered prompt, response), independent of whatever subagent mechanism
Claude Code offers in the future.

**Recommendation:** rendered system prompt + flags. It keeps the
engine/executor boundary clean (CLAUDE.md: "agents sit behind an executor interface") —
the executor interface needs only `execute(profile, inputs) -> response`, with zero
Claude-Code-specific filesystem side effects.

**Status: Verified at the mechanism level** (P0 spike,
`docs/spikes/claude-p-feasibility.md`). `--append-system-prompt` was accepted without
error across every live call. Whether persona text measurably changes model behavior
wasn't isolated (would need an A/B comparison) — that's ordinary prompt iteration
during T4.2, not a CLI-feasibility blocker, so it isn't re-flagged as Assumed.

---

## 3. Architecture

### 3.1 Components and module layout for `src/orchestrator/`

Layer-oriented (O-9). `config/defaults.*`, `agents/profiles/`, `templates/`,
`fixtures/mock/` stay at the orchestrator repo root per §8; paths to them are resolved
by walking up from `__file__` to the repo root (G-11 — sufficient for the
"clone, used unmodified" prototype deployment of §5.1; packaging as installed-package
data is a production-path concern, not built now).

```
src/orchestrator/
├── __init__.py                # __version__
├── cli/
│   ├── main.py                 # entry point, argument parsing, dispatch
│   └── commands/                # one module per CLI command (register, validate, run,
│                                 #   approve, reject, answer, stop, runs_list, runs_show)
├── config/
│   ├── loader.py                # TOML load (tomllib) + defaults/project/scenario assembly
│   ├── schema.py                 # pydantic models for defaults/project/scenario config
│   └── validate.py               # `orchestrator validate`; hardening-tightens-only check
├── models/
│   ├── run.py                    # RunRecord, RunState, RunOutcome
│   ├── graph.py                  # StageSpec, StageStatus, GraphState
│   ├── traceability.py           # FR, AC, DD, Task, commit-trailer models
│   ├── decisions.py              # Decision, DecisionLineage
│   ├── approvals.py              # ApprovalCheckpoint, ApprovalRecord
│   ├── events.py                 # Event, EventType, hash-chain entry
│   └── agent_io.py               # AgentCallRequest, AgentCallResponse (small execution
│                                  #   summary only, O-4 — stage outputs are read from
│                                  #   workspace files, not this response)
├── engine/
│   ├── graph.py                   # the fixed Phase 1 stage graph (StageSpec list + edges)
│   ├── runner.py                   # StageRunner: entry gate → execute → exit gate →
│   │                                #   policies → event → commit
│   ├── fsm.py                       # run-level state machine + the shared drive() entry
│   │                                #   point used by run/approve/reject/answer
│   ├── scheduler.py                  # parallel join handling (S5, S7): thread pair + join
│   ├── replanning.py                  # rejection-driven re-planning (invalidate + re-run)
│   └── locking.py                      # per-project run lock (PID + staleness, G-2)
├── stages/                              # one thin module per stage binding a StageSpec
│   ├── s0_prepare.py … s8_release.py
├── gates/
│   ├── base.py                          # Gate protocol
│   ├── schema_gate.py                    # pydantic-model validation of the stage's
│   │                                       #   output files read from the workspace (O-4)
│   ├── command_gate.py                    # subprocess gates: tests, coverage, lint,
│   │                                       #   types, audit
│   ├── existence_gate.py                   # S2 file/symbol existence check
│   ├── traceability_gate.py                 # FR/DD/Task citation checks
│   └── approval_gate.py                      # blocks on a pending approval
├── policies/
│   ├── base.py                                # Policy protocol
│   ├── workspace_confinement.py, path_partitioning.py, protected_paths.py,
│   │   dependency_control.py, schema_change_control.py, secret_scan.py,
│   │   diff_size_limit.py, main_protection.py
├── executors/
│   ├── base.py                                 # Executor protocol
│   ├── real.py                                  # `claude -p` subprocess executor
│   └── mock.py                                   # fixture replay: materializes fixture
│                                                    #   files into the workspace + generic
│                                                    #   fallback (O-8)
├── profiles/
│   ├── loader.py                                  # loads agents/profiles/*.toml
│   └── render.py                                   # renders persona/context into a prompt
├── workspace/
│   ├── manager.py                                   # clone/init, run branch, venv setup
│   └── git_ops.py                                    # commit-with-trailers, diff,
│                                                        # confinement snapshot, the
│                                                        # serialized-commit lock (G-3)
├── audit/
│   ├── event_log.py                                    # hash-chained events.jsonl
│   ├── run_record.py                                    # atomic run.json/graph.json I/O
│   ├── metrics.py                                        # metrics.json from events
│   ├── report.py, pr_description.py                       # report.md, pr-description.md
├── registry.py                                             # ~/.orchestrator/projects.*
└── exceptions.py                                             # domain exceptions
```

### 3.2 Engine / control-flow model

#### 3.2.1 Pause and resume across CLI commands (closes G-1, G-2)

There is no persistent orchestrator process. Every CLI command that touches a run —
`run`, `approve`, `reject`, `answer` — funnels into one shared function,
`engine.fsm.drive(run_id, incoming_event)`:

1. Acquire the project lock (§3.2.1 staleness rule below decides whether a stale lock
   can be reclaimed).
2. Load `run.json` + `graph.json` from disk — this **is** the run's entire state; nothing
   survives in memory between commands.
3. If resuming (`approve`/`reject`/`answer`), validate the run is actually
   `awaiting_approval` at the specific checkpoint being resolved (defends against a
   stale or misdirected command), append the decision to `approvals.jsonl` and an event.
4. Re-enter the stage loop, continuing from the next stage after the checkpoint (or
   starting at S0 for a fresh `run`).
5. Drive stages synchronously until the run hits a checkpoint (write
   `awaiting_approval`, exit), a terminal state (`completed`/`failed`/`rejected`/
   `stopped`, exit), or an unrecoverable error (exit with a clear message).
6. Release the lock whenever control returns to the CLI — i.e. the lock is **never**
   held across a process boundary at a normal pause point.

This means "pause" is just "process exit while `graph.json` says `awaiting_approval`,"
and "resume" is "reload state, re-enter the same driver." Phase 1 needs nothing else for
the common case; genuine mid-stage crash recovery (process killed while a `claude -p`
call is in flight) stays Phase 2 (C9-AC4, SHOULD) by design, and is the only case left
uncovered — but because the lock is timestamped, a dead mid-stage lock is at least
detectable and forcibly clearable, so it can't permanently block the project even before
real resume is built (G-2): a lock is reclaimable if its PID is no longer live, or its
age exceeds `max_run_duration`.

#### 3.2.2 Parallel stages: git and the event log (closes G-3)

S5a/S5b (and S7a/S7b) run as two threads, each blocking on one `claude -p` subprocess
call (O-5). Path partitioning (§7.3, DECIDED) keeps their *file edits* disjoint, but two
shared, order-sensitive resources are not protected by path partitioning alone: the git
working tree's index/HEAD, and the hash-chained event log (each entry's hash depends on
the previous entry's).

The rule applied throughout: **only "wait on the external agent call" is concurrent;
every side effect the orchestrator itself performs in response is serialized.**
Concretely:
- A single `EventLog` instance per run, guarded by one `threading.Lock`. Both stage
  runners append `stage_started`/`gate_result`/`stage_finished` events through the same
  serialized writer, even though the two subprocess calls they're waiting on overlap in
  wall-clock time.
- A single `git_ops.SerializedGit` per workspace, guarded by one lock. Each thread stages
  and commits **only the paths its own `StageSpec` owns** (`git add <owned-paths>`, never
  `git add -A`), so even if a commit interleaves with the other branch's still-uncommitted
  work, the commit's *contents* stay within that stage's partition — the lock only
  prevents two `git commit` calls from executing at the literal same instant, it doesn't
  need to prevent interleaved *writing*, because writing is already confined by path
  partitioning.
- Commit order between the two branches is not significant — the Join gate (C4-AC2)
  checks "did both branches finish successfully," not which committed first.
- `scheduler.py` starts both threads, `.join()`s both, collects both outcomes, and only
  then evaluates the join gate in a single-threaded continuation — gate evaluation itself
  needs no concurrency control.

Git-worktree isolation (§7.3's "cleaner alternative") stays COULD/deferred; the
serialization above is sufficient for two-way parallelism at prototype scale and avoids
building a second isolation mechanism under time pressure.

### 3.3 Core abstractions and their interfaces

Interface sketches, not implementations — the actual code is out of scope for this
document.

| Abstraction | Interface | Notes |
|---|---|---|
| `Executor` | `execute(profile: AgentProfile, request: AgentCallRequest) -> AgentCallResponse` | `real` and `mock` implementations; engine code depends only on this (C8-AC1). `AgentCallResponse` is a small summary (`produced_ids`, `files_written`) — deliverables are written by the agent's own tools into the workspace (O-4, revised). |
| `Gate` | `check(context: StageContext) -> GateResult` | `GateResult(ok, details, violations)`; reads the stage's output files from the workspace, not from `AgentCallResponse` (O-4). |
| `Policy` | `check(context: RunContext, diff: WorkspaceDiff) -> PolicyResult` | `PolicyResult(ok, evidence, outcome)`; parameters come from layered config (O-7). |
| `StageSpec` | declarative: `id`, `owner_profile`, `depends_on`, `entry_gates`, `exit_gates`, `allowed_write_paths`, `commit_strategy` | One per stage, not a package (O-9). |
| `StageRunner` | `run(spec: StageSpec, context: RunContext) -> StageResult` | Entry gate → executor call(s) (looped per-task for S5a) → exit gate → policies → event → commit. |
| `EventLog` | `append(event: Event) -> None`; `verify() -> bool` | Computes/checks the hash chain (D-7). |
| Run-record store | atomic `read`/`write` for `run.json`, `graph.json` | Write-temp-then-`os.replace` (O-2). |
| `ApprovalCheckpoint` | pause-point definition + `resolve(decision, feedback) -> None` | Drives `engine.replanning` when a non-`--final` rejection carries feedback (G-9). |

---

## 4. Build plan (Phase 1)

**D-19 revised (reviewer decision).** The ~12h build is a **vertical slice**, not a
breadth-first pass at every Phase-1 MUST item: it must reach the real executor and all
three showcase runs, not stop at a mock-only skeleton. To make that fit, specific items
are deliberately trimmed rather than sequenced-but-deferred (contrast with the prior
revision of this section) — each trim is called out where it happens in §4.1 and
collected as an explicit limitations list in §4.3. Phase 2 still doesn't start until the
remaining Phase-1 MUST surface (the trimmed items) is built afterward.

### 4.1 Ordered task list

Tasks are grouped into work blocks sized for one engineer working with agent assistance
— most of the actual typing is expected to happen via Claude Code, so effort reflects
supervised AI-assisted pace, not solo hand-writing. Each block lists what it depends on
and the capability/AC IDs (or gap/O-numbers) it closes.

| # | Task | Depends on | Effort (h) | Traces to |
|---|---|---|---|---|
| P0 | Spike: confirm `claude -p` flags — JSON output, system-prompt injection, directory/tool restriction, and that it reliably writes files via its own tools under an instructed layout | — | 0.5 | Validates O-4, O-6, O-10 |
| T1 | **Foundations** — domain models (pydantic); config loader + `validate` (schema errors only, C1-AC1 as literally stated — no hardening-merge logic, §9 stays COULD); hash-chained event log + atomic run-record I/O; executor protocol + mock executor incl. fixture file-materialization (O-8) | — | 1.5 | C2-AC2, C1-AC1, C2-AC1/AC3, C12-AC1/AC2 (§11), C8-AC1, C1-AC3 |
| T2 | **Engine walking skeleton** — static graph data; `StageRunner` (single stage); workspace manager (greenfield init, existing-repo clone at base ref, venv); CLI entry + `run`/`register`/`validate`; S0→S1 pause/resume proven end to end | T1 | 1.75 | C4-AC1/AC4; C1 (register); C3-AC1–AC5 (closes G-12) — **validates O-1/O-2's pause/resume design** |
| T3 | **Approvals + full graph** — `awaiting_approval` state, `approve`/`reject`/`answer`/`stop`, lock acquire/release with staleness recovery (§3.2.1, closes G-1/G-2); S0–S8 stub gates incl. Change-control + Release checkpoints | T2 | 1.25 | C7-AC1–AC4, C1; C4-AC3, C5-AC1–AC3 |
| T4 | **Real executor + agent profiles** — profile rendering (O-10); tool-based artifact writes + JSON-summary parsing (revised O-4); per-call timeout; dir/tool restriction (O-6); 7 profiles authored for the tool-based-write contract | P0, T1, T3 | 1.5 | C8-AC1–AC6, C9-AC5 |
| T5 | **Greenfield template + target repo prep** — `templates/python-service/` incl. CI workflow + `.orchestrator/` example; create the empty `shortener-greenfield-by-agents` repo; add `.orchestrator/` to A1 (`url-shortener-ai-assisted`); tag `baseline-greenfield` on A1; check whether A1's own tests need Postgres; author scenario REQ text incl. B-1's broadened reliability behavior and the brownfield fault-injection flag (G-16) | T2 | 0.75 | §12 setup, C3-AC2 — **at-risk, see §4.3** |
| T6 | **Parallel join + policies** — threaded S5/S7 scheduler with serialized git-commit + event-log writer (§3.2.2, closes G-3); 7 policies: workspace confinement, path partitioning, protected paths (G-4/G-5), main protection, secret scan (G-7), schema change control, diff-size limit | T3, T1 | 1.75 | C4-AC2 (§7.3); C6-AC1/AC2 for 7 of 8 policies — **only dependency control descoped → limitation, §4.3** |
| T7 | **Reliability + re-planning** — bounded retries incl. G-13's one-fix-call-per-attempt + `Stage: S5a-fix` trailer; per-call timeout enforcement; rollback to checkpoint commit (G-14); `stop`; simple duration/call-count checks; fallback-to-human on exhaustion; design-rejection re-planning (C11); G-16's fault-injection hook (orchestrator writes one failing acceptance test before S6 attempt 1 when the scenario flags it, `injected: true`) | T3 | 1.0 | C9-AC1–AC3/AC5; C11-AC1–AC3 (design-rejection only — **G-9's broader extension → limitation, §4.3**) |
| T8 | **Traceability, lineage, metrics, reporting** — citation gates; commit trailers incl. `S5a-fix` (G-13); `traceability.md`; `decisions.jsonl`; S7b→S5a loop invalidates S6/S7a/S7b (G-15); `metrics.json`; `report.md`; `pr-description.md` | T3, T6 | 1.25 | C10-AC1–AC6; C13-AC1; C12-AC5 |
| T9 | Coverage / gap-filling pass on the orchestrator's own tests | rolling | 0.5 | C15-AC1/AC2 |
| T10 | **Three showcase runs** — start greenfield the moment T4/T5/T7/T8 clear, don't wait on anything else; greenfield (real executor, derive mock fixtures per D-21/O-8, commit to `evidence/runs/`); brownfield (baseline check, migration → change-control approval, fault-injected retry per G-16); ambiguous (blocking questions → clarification → answer, design rejection → re-plan) | T4, T5, T7, T8 | 1.25 | §12 all three rows; D-21; C15 — **tightest margin, see §4.3** |
| T11 | Final polish — `runs list`/`runs show` formatting; full `scripts/check.py` pass | T10, T12 | 0.5 | C1-AC4, C15 |
| T12 | **Documentation** — README (setup, testing approach); `docs/architecture.md` (components, orchestration model, control flow, key decisions — assignment deliverable); `docs/engineering-summary.md` (plan/rationale, artifacts, risks/trade-offs, assumptions, limitations, pulling directly from §4.3's limitations list) | T8 | 1.0 | §19 mapping; assignment §5 deliverables — **written while T10's runs execute, see §4.2** |

**Total effort: ~14.5h** across P0 + 12 blocks. **Critical-path wall-clock: ~12.0h** — T12
overlaps T10's wall-clock window rather than adding to it (§4.2), which is what keeps this
inside the ~12–13h target despite T6 growing (5→7 policies) and T12 being new.

### 4.2 Critical path

```
P0 → T1 → T2 → T3 → T4 → T5 → T6 → T8 → T10 → T11
                                        └──(parallel)──→ T12 ──┘
```

T7 (reliability + re-planning) only needs T3 and can run in parallel with T4–T6, since
it's an independent extension of the same `StageRunner` points; it just has to land
before T10 (the showcase runs exercise retries, rollback and design rejection). T9
(coverage) is not a separate critical-path node — it rides along with every block per
CLAUDE.md's "every change ships with tests," with the 0.5h being catch-up time for gaps,
not the total testing effort. T5 (template + target repo prep) only needs T2's workspace
manager and can start in parallel with T3/T4 — it's real-world git/GitHub work, not
engine code, so it doesn't compete for the same attention as T3/T4.

**T12 is deliberately off the critical path.** T10's 1.25h is dominated by real
agent think-time (waiting on `claude -p` across nine stages × three scenarios), not
hands-on-keyboard time — so T12's 1.0h of documentation writing happens *during* that
wait, using what's already been built (through T8) as source material, rather than
queuing up after T10 finishes. T11 (final polish) waits on both, since `runs list`/
`runs show` needs the showcase runs' data and the final `scripts/check.py` pass should
run after the docs are in.

### 4.3 Where scope is at risk, given ~12–13 hours

**This slice is scoped to finish, not to sequence-and-defer** — the reviewer's D-19
revision means real Claude execution and all three showcase scenarios are the
deliverable, not a stretch goal. Getting there within budget required trimming specific
Phase-1 MUST surface area. Every trim below is a genuine limitation, not a documentation
gap, and belongs in the engineering summary's limitations section verbatim.

**Limitations (for the engineering summary):**

1. **C6 — 1 of 8 policies not built.** Dependency control is designed (§1.1, §2 O-7) but
   not implemented in this slice. The other seven — workspace confinement, path
   partitioning, protected paths, main protection, secret scan, schema change control,
   and diff-size limit — are all built; schema change control specifically is required
   in-scope because the brownfield showcase's migration needs to trigger
   Change-control approval (§12). A change that adds an unapproved dependency will not
   be caught by policy in this build.
2. **C11 — re-planning covers design rejection only.** The literal C11 AC (rejecting the
   design re-runs S3 onward) is built; the broader extension this proposal designed for
   Change-control and Release rejection (G-9) is documented but not implemented —
   rejecting either of those checkpoints in this build ends the run rather than
   re-planning it.
3. **C9 — duration/call limits are simple fixed checks**, not the more configurable
   per-role/per-stage budgeting the project-hardening layer (§9, COULD) eventually
   wants. Not a capability gap against C9's stated ACs, noted for completeness only.

**At-risk items (schedule, not scope):**

- **T5 (target repo prep) is the single most unpredictable item.** Whether A1's existing
  test suite needs a running Postgres instance is unknown until checked; if it does,
  satisfying C3-AC4's "baseline gates pass" for the brownfield/ambiguous scenarios needs
  either a throwaway DB provisioned in the workspace or a narrowed baseline-gate scope
  (e.g. excluding DB-dependent tests) — neither is budgeted. This is the item most
  likely to need a real-time scope call mid-session.
- **T4 (real executor) remains the highest-uncertainty engineering task**, for the same
  underlying reasons as before (O-4/O-6/O-10 are all "Assumed") — though O-4's revision
  to tool-based writes is expected to lower this risk relative to the dropped
  fenced-JSON approach, since it asks the model to work the way Claude Code already
  works natively rather than obey a bespoke response-format contract.
- **T10 (three showcase runs) has the least slack.** Its 1.25h is wall-clock bound by
  real agent think-time across nine stages × three scenarios, and G-16's fault injection
  has to land cleanly for the brownfield retry to demonstrate what it's meant to. Run
  greenfield first — it's also what derives the mock fixtures the other two scenarios'
  own tests lean on. If a real run misbehaves, the fix is to report honestly what
  completed and what didn't, not to let one bad run silently eat the time budgeted for
  the other two.
