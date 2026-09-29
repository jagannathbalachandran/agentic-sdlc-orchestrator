"""S3 Design & architecture — StageSpec binding (requirements.md §7).

Design approval is unconditional (C7: "Design (always)") — wired directly.
"""

from __future__ import annotations

from orchestrator.models.approvals import ApprovalCheckpointKind
from orchestrator.models.graph import CommitStrategy, StageId, StageSpec

SPEC = StageSpec(
    stage_id=StageId.S3_DESIGN,
    owner_profile="architect",
    depends_on=(StageId.S2_CODEBASE_ANALYSIS,),
    allowed_write_paths=("02-design.md", "docs/architecture.md"),
    commit_strategy=CommitStrategy.ONE,
    checkpoint_after=ApprovalCheckpointKind.DESIGN,
)
