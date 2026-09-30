"""S8 Release readiness — StageSpec binding (requirements.md §7).

The join point after S7a/S7b's parallel pair (T6.1) — depends on *both*, not
just S7b, so the scheduler never starts S8 while the other sibling branch is
still running.

Release approval is unconditional (C7: "Release (always)") — wired directly.
The push itself (after approval) isn't part of the stage graph's own pending-
stage loop; it's a separate action once the run reaches `completed`.

Owner "Orchestrator + human": `requires_agent=False` — no agent call.
`report.md`/`pr-description.md` are generated here (engine/fsm.py's S8
commit hook) so the human has them to read *before* deciding on Release
approval, matching requirements.md's own S8 row ("Checklist, report.md,
pr-description.md (-> record)").
"""

from __future__ import annotations

from orchestrator.models.approvals import ApprovalCheckpointKind
from orchestrator.models.graph import CommitStrategy, StageId, StageSpec

SPEC = StageSpec(
    stage_id=StageId.S8_RELEASE,
    owner_profile=None,
    depends_on=(StageId.S7A_DOCS, StageId.S7B_REVIEW),
    commit_strategy=CommitStrategy.NONE,
    checkpoint_after=ApprovalCheckpointKind.RELEASE,
    requires_agent=False,
)
