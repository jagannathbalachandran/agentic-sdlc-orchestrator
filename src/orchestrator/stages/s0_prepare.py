"""S0 Prepare — StageSpec binding (requirements.md §7)."""

from __future__ import annotations

from orchestrator.models.graph import CommitStrategy, StageId, StageSpec

SPEC = StageSpec(
    stage_id=StageId.S0_PREPARE,
    owner_profile=None,
    depends_on=(),
    allowed_write_paths=("00-source.md",),
    commit_strategy=CommitStrategy.ONE,
)
