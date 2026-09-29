"""S5a Implement + unit tests — StageSpec binding (requirements.md §7).

Depends on S4 in the real design (runs in parallel with S5b, joined before S6).
Depends on S4 here too, but S5b is chained *after* S5a (not parallel) as a T3.2
simplification — T6.1's scheduler makes both depend on S4 directly and run
concurrently.
"""

from __future__ import annotations

from orchestrator.models.graph import CommitStrategy, StageId, StageSpec

SPEC = StageSpec(
    stage_id=StageId.S5A_IMPLEMENT,
    owner_profile="developer",
    depends_on=(StageId.S4_PLAN,),
    commit_strategy=CommitStrategy.ONE_PER_TASK,
)
