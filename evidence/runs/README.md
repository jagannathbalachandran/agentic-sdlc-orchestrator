# Real-run evidence — greenfield scenario

This folder holds the records of the orchestrator's **real** runs: real
`claude -p` agents, real gates and a real test suite at S6. Each run folder is
a copy of the orchestrator's run record, with the local username redacted.

---

## Start here — the completed run

The pipeline completed end to end with real agents in the **automated
verification run** (checkpoints approved automatically and labelled — see
[below](#automated-verification-run--completed-end-to-end) for how it differs
from the human-approved runs). Everything it produced is browsable here:

| What | File |
|---|---|
| Original requirement (frozen at S0) | [00-source.md](VERIFY-verify-greenfield-greenfield-minimal-20260930-001/workspace/00-source.md) |
| Requirements: FRs and acceptance criteria — analyst (S1) | [01-requirements.md](VERIFY-verify-greenfield-greenfield-minimal-20260930-001/workspace/01-requirements.md) |
| Design: technology stack, design decisions, contracts — architect (S3) | [02-design.md](VERIFY-verify-greenfield-greenfield-minimal-20260930-001/workspace/02-design.md) |
| Architecture document created by the architect | [docs/](VERIFY-verify-greenfield-greenfield-minimal-20260930-001/workspace/docs) |
| Plan: tasks under each FR, citing design decisions — planner (S4) | [03-plan.md](VERIFY-verify-greenfield-greenfield-minimal-20260930-001/workspace/03-plan.md) |
| Code — developer (S5a), one call and one commit per task | [src/](VERIFY-verify-greenfield-greenfield-minimal-20260930-001/workspace/src) |
| Unit tests (developer) and acceptance tests (test engineer, S5b) | [tests/](VERIFY-verify-greenfield-greenfield-minimal-20260930-001/workspace/tests) |
| Code review findings — reviewer (S7b) | [04-review-findings.md](VERIFY-verify-greenfield-greenfield-minimal-20260930-001/workspace/04-review-findings.md) |
| Service README — technical writer (S7a) | [README.md](VERIFY-verify-greenfield-greenfield-minimal-20260930-001/workspace/README.md) |
| Traceability: FR → AC → DD → task → commit → test | [traceability.md](VERIFY-verify-greenfield-greenfield-minimal-20260930-001/workspace/traceability.md) |
| Per-task commits with `Task` / `FR` / `Req` / `Run` / `Stage` trailers | [commits-with-trailers.txt](VERIFY-verify-greenfield-greenfield-minimal-20260930-001/commits-with-trailers.txt) |
| Release report and PR description | [report.md](VERIFY-verify-greenfield-greenfield-minimal-20260930-001/report.md), [pr-description.md](VERIFY-verify-greenfield-greenfield-minimal-20260930-001/pr-description.md) |
| Approvals, hash-chained events, metrics | [approvals.jsonl](VERIFY-verify-greenfield-greenfield-minimal-20260930-001/approvals.jsonl), [events.jsonl](VERIFY-verify-greenfield-greenfield-minimal-20260930-001/events.jsonl), [metrics.json](VERIFY-verify-greenfield-greenfield-minimal-20260930-001/metrics.json) |
| Agent transcripts: prompt and response for every call | [agents/](VERIFY-verify-greenfield-greenfield-minimal-20260930-001/agents) |
| Full git history of the run branch | `workspace.bundle` — `git clone workspace.bundle verify-workspace` |

Everything in `workspace/` was committed on the run branch except
`traceability.md` (generated after the final S8 commit) and
`04-review-findings.md` (S7b's output, not committed); both were copied from
the run's workspace.

The three **human-approved** runs (001–003) below show the checkpoints I
reviewed and the bugs each run exposed on the way to this result.

---

## Summary

| Run | Approvals | Got as far as | Outcome | Root cause | Fixed in |
|---|---|---|---|---|---|
| `greenfield-minimal-20260930-001` | Human (design **rejected** with feedback) | S3 re-run after rejection | failed | Rejection feedback never reached the re-run; re-plan inherited an exhausted retry budget | `adf9550` and related commits |
| `greenfield-minimal-20260930-002` | Human (design approved) | S5a, before any agent call | failed | S5a's plan parser had drifted from the S4 gate's parser | `5b51f29` |
| `greenfield-minimal-20260930-003` | Human (design approved) | S5a, during developer calls | failed | Plan parser kept only the first line of each task, so the developer received truncated instructions | `c7ed024` |
| `VERIFY-verify-greenfield-greenfield-minimal-20260930-001` | **Automated**, labelled `claude-code-verification` | **all 9 stages** | **completed** | — | `6fd9032`, `6dea461`, `0839ae4` (bugs found during this run) |

**Progress across runs:** S3 → S5a (no agent call) → S5a (real developer
work) → **completed** (automated verification).

The sequence is the evidence: each real run exposed an integration bug that
the mock-based test suite (280–330 tests) had not; the run record was enough to
diagnose it; the fix was made and tested before the next run.

---

## What worked from the first real run onward

- **S0** built the workspace from the approved template, with a run branch and
  a venv.
- **S2 skipped for greenfield** with a recorded reason (C4-AC3).
- **Analyst (S1):** FRs citing the REQ, testable given/when/then acceptance
  criteria, explicit assumptions, no invented scope.
- **Architect (S3):** contracts per endpoint, 302 redirects with reasoning,
  CSPRNG codes with collision retry.
- **Planner (S4):** tasks under each FR, each citing a design decision, with
  dependencies.
- **Pause/resume across processes** at the Design checkpoint, every approval
  recorded, hash-chained events.
- **Governance respected by an agent:** in run 003 the architect read
  `approved_dependencies = []` and designed with the standard library only,
  explicitly to avoid an unapproved dependency.

---

## Run 001 — design rejection exposed four bugs

**What happened.** Requirements and design were produced. At the Design
checkpoint I rejected the design with feedback: it named no technology stack
and used TypeScript-style interface sketches for a Python template — a real
risk, since S5a and S5b build from the same contracts in parallel. S3 re-ran
and failed; the run ended `failed`.

**How it was diagnosed** (from `events.jsonl`; transcripts were not yet
recorded, so this run has no `agents/` folder):

| Finding | Evidence in the record |
|---|---|
| Re-run counted as S3 attempt 2 of 2, so one failure ended the run | `stop` event: "S3 failed after 2 attempt(s)" |
| Design citation gate passed while finding **zero** design decisions | `gate_result`: `"passed": true, "details": "0 DD(s) cite an FR"` on a design with DD-1..DD-4 |
| No transcripts, scenario snapshot, effective config or artifact hashes in the record | Run folder contents vs requirements §11 |
| Design unchanged after the rejection | `02-design.md` in the workspace was byte-for-byte the original |

**Root cause (diagnosed by Claude Code):** the design-rejection path re-ran
S3 but never saved the rejection comment where the prompt builder could read
it, so S3 got an identical prompt and produced an identical design. The retry
limit was computed from cumulative attempts, so the re-plan had no budget
left.

**Fixes:** rejection feedback passed to the re-run; a fresh retry budget per
re-plan cycle; citation gates parse real headings and fail on zero items; a
gate that fails any retry which changes nothing; an architect profile rule
and a new gate requiring a Technology stack section; agent transcripts,
scenario/config snapshots and artifact hashes recorded; outcome and error text
on `stage_finished` events. Checking this run's real `metrics.json` against
the code found and fixed two counting bugs (a skipped stage counted as a
first-pass failure; automatic retries emitting no retry event).

---

## Run 002 — two parsers disagreed

**What happened.** The design came back with an explicit **Technology stack**
section (Python 3.11+, Flask `>=3.0,<4.0`, Flask test client) and Python
signatures — the new gate and the feedback fix working. I approved. The plan
passed S4. S5a failed twice immediately.

**How it was diagnosed:** `stage_finished` now carried the error:
`"outcome": "invalid_output", "error": "03-plan.md has no parseable tasks"` —
while S4's gate had passed the same file, which followed the documented format
exactly.

**Root cause:** separately maintained copies of the plan/requirements parsing
logic had drifted; only the S4 gate's copy accepted real headings with a title
(`## FR-1: <title>`).

**Fix (`5b51f29`):** one shared parser used by the S4 gate, S5a's per-task
loop and the traceability generator; S4 now fails if it finds zero tasks, so a
bad plan is caught where the planner can retry.

---

## Run 003 — truncated instructions to the developer

**What happened.** The architect chose a standard-library WSGI design to stay
within the empty approved-dependency list. I approved. The plan passed S4. S5a
ran real developer calls, then failed with `invalid_output` on both attempts.

**How it was diagnosed — in two minutes, from the new transcripts:**

```
agents/S5a-1-T-1.3.json  "prompt": "Implement plan task T-1.3 (cites DD-3, under FR-1):
                                    Implement the thread-safe in-memory `URLStore` in\n\n..."
agents/S5a-2-T-1.2.json  "prompt": "Implement plan task T-1.2 (cites DD-3, under FR-1):
                                    Implement CSPRNG short-code generation —\n\n..."
```

The task text was cut off mid-sentence: the developer never received the
file paths or the rest of the task.

**Root cause:** the plan parser captured only the first line of each task
entry; the planner's task entries wrapped across several lines.

**Fixes (`c7ed024`):** the plan parser keeps the full multi-line task text;
`invalid_output` records the error and a snippet of the raw reply; summary
parsing extracts the JSON summary from a longer reply; an S5a retry resumes at
the failed task instead of redoing committed ones.

---

## Automated verification run — completed end to end

**Run:** `greenfield-minimal-20260930-001` in project `verify-greenfield`
(folder `VERIFY-verify-greenfield-greenfield-minimal-20260930-001`).

Run by Claude Code, at my instruction, with the **real executor**, in a
throwaway target repo and a separate ORCH_HOME. Checkpoints were approved
automatically and are labelled `claude-code-verification` / "AUTOMATED
VERIFICATION" in `approvals.jsonl`. It is **not** a human-approved showcase
run: it shows the pipeline working end to end with real agents after the fixes
from runs 001–003.

**Result:** `completed` — all nine stages passed; real per-task commits with
correct `Task`/`FR`/`Req` trailers; **S6 recovered through two real retries**
(test failure → developer fix call → re-verify); `traceability.md` generated
with commits linked to tasks.

**Bugs found and fixed during this run:**
- `6fd9032` — a relative `--orch-home` was resolved twice, crashing venv
  creation in S0.
- `6dea461` — three subprocess calls decoded output with the Windows cp1252
  codepage instead of UTF-8, crashing on em dashes and smart quotes in real
  agent content.
- `0839ae4` — `traceability.md` never linked commits to tasks, reporting "no
  commit" for every FR despite correctly trailered per-task commits.

---

## About workspaces

Workspaces are disposable: built from the approved template (greenfield) or
cloned from the target at its base ref (existing codebases). By design nothing
is pushed to a target repo without Release approval; runs 001–003 never
reached Release. The verification run's push went only to its throwaway local
target and failed harmlessly; its full history is included as
`workspace.bundle` and its files under `workspace/`.

---

## Lessons

1. **Mock tests passed; real runs failed — for the same reason each time.**
   Parsing and gate logic had been tested against fixture formats written by
   the same developer (Claude Code), not against what a real agent writes.
   Real agents add titles to headings and wrap long lines. Each real run found
   the next instance.
2. **Observability paid for itself.** Run 001 couldn't be fully diagnosed
   because transcripts weren't recorded. Once they were, run 003's cause was
   visible directly in the recorded prompt.
3. **Human checkpoints caught what gates didn't.** The missing technology
   stack in run 001's design passed every gate; the human rejection turned it
   into a permanent platform rule and a new gate.
4. **Governance shaped agent behaviour.** Given an empty approved-dependency
   list, the architect in run 003 designed around it rather than adding a
   dependency.
5. **Some bugs only appear with real content on a real machine.** Windows text
   encoding and path handling were invisible to tests that used ASCII fixtures
   and absolute paths.

---

## How to inspect a run

```powershell
$rec = "evidence\runs\<run-folder>"
Get-Content "$rec\run.json"                                            # identity, outcome, config hash
Get-Content "$rec\events.jsonl" | Select-String "stop|stage_finished"  # what happened
Get-Content "$rec\approvals.jsonl"                                     # decisions and comments
Get-Content "$rec\metrics.json"                                        # metrics
Get-ChildItem "$rec\agents"                                            # prompt + response per agent call (runs 002+)
```