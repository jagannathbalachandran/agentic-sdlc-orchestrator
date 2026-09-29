"""S4 Plan — StageSpec binding (requirements.md §7)."""

from __future__ import annotations

from orchestrator.models.graph import CommitStrategy, StageId, StageSpec

SPEC = StageSpec(
    stage_id=StageId.S4_PLAN,
    owner_profile="planner",
    depends_on=(StageId.S3_DESIGN,),
    allowed_write_paths=("03-plan.md",),
    commit_strategy=CommitStrategy.ONE,
)
