"""S5b Acceptance tests — StageSpec binding (requirements.md §7).

Chained after S5a for now (T3.2's "no parallel yet" scope) rather than running
concurrently with it — T6.1's scheduler restores the real parallel-join shape
(both depending on S4 directly).
"""

from __future__ import annotations

from orchestrator.models.graph import CommitStrategy, StageId, StageSpec

SPEC = StageSpec(
    stage_id=StageId.S5B_ACCEPTANCE_TESTS,
    owner_profile="test_engineer",
    depends_on=(StageId.S5A_IMPLEMENT,),
    commit_strategy=CommitStrategy.ONE,
)
