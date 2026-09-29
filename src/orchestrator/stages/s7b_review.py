"""S7b Review — StageSpec binding (requirements.md §7).

Chained after S7a for now (T3.2's "no parallel yet" scope) rather than running
concurrently with it — T6.1's scheduler restores the real parallel-join shape.
"""

from __future__ import annotations

from orchestrator.models.graph import CommitStrategy, StageId, StageSpec

SPEC = StageSpec(
    stage_id=StageId.S7B_REVIEW,
    owner_profile="reviewer",
    depends_on=(StageId.S7A_DOCS,),
    commit_strategy=CommitStrategy.NONE,
)
