"""S8 Release readiness — StageSpec binding (requirements.md §7).

Release approval is unconditional (C7: "Release (always)") — wired directly.
The push itself (after approval) isn't part of the stage graph's own pending-
stage loop; it's a separate action once the run reaches `completed`.
"""

from __future__ import annotations

from orchestrator.models.approvals import ApprovalCheckpointKind
from orchestrator.models.graph import CommitStrategy, StageId, StageSpec

SPEC = StageSpec(
    stage_id=StageId.S8_RELEASE,
    owner_profile=None,
    depends_on=(StageId.S7B_REVIEW,),
    commit_strategy=CommitStrategy.NONE,
    checkpoint_after=ApprovalCheckpointKind.RELEASE,
)
