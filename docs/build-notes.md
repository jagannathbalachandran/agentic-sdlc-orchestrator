# Build notes

Short per-task log: what changed, ACs covered, anything deferred or assumed. One
entry per task from `docs/tasks.md`, in build order.

## P0 — `claude -p` feasibility spike

**What changed:** ran 4 live `claude -p` calls against a scratch git repo
(`/tmp/spike-target`) via a Python driver with `subprocess` timeouts, per
`docs/tasks.md` P0's constraints. No orchestrator code touched. Output:
`docs/spikes/claude-p-feasibility.md`.

**Covered:** validates O-4, O-6, O-10 (`docs/architecture-proposal.md` §2).

**Findings / deferred / assumed:**
- O-4 upgraded **Assumed → Verified**: tool-based write + small JSON summary worked
  exactly as designed, first attempt.
- O-6 **stays partially Assumed, recommendation changed**: `--add-dir` alone does
  **not** confine writes (a live test wrote outside it without any denial);
  `--restricted` does block it, but the observed refusal looked like model judgment,
  not a confirmed hard technical denial (`permission_denials` stayed empty). The
  post-stage diff+hash check remains the real enforcement point, unchanged.
- O-10 upgraded **Assumed → Verified at the mechanism level**: `--append-system-prompt`
  accepted without error; persona-fidelity itself not isolated (ordinary prompt
  iteration during T4.2, not a blocker).
- **Constraint deviation:** the reviewer's constraint said "cap with `--max-turns`" —
  no such flag exists in `claude` 2.1.268. Used `--max-budget-usd` + the subprocess
  `timeout` instead. Flagged for review at hard stop (a).
- `architecture-proposal.md`'s O-4/O-6/O-10 status paragraphs updated in place to
  point at the spike doc.
