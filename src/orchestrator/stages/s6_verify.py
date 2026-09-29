"""S6 Verify — StageSpec binding (requirements.md §7).

Change-control approval is conditional on a risky change (migration / new
dependency / protected path / large diff) — that detection needs the diff-size
and dependency-control policies (T6.2), so no checkpoint is wired here yet.
"""

from __future__ import annotations

from orchestrator.models.graph import CommitStrategy, StageId, StageSpec

SPEC = StageSpec(
    stage_id=StageId.S6_VERIFY,
    owner_profile=None,
    depends_on=(StageId.S5B_ACCEPTANCE_TESTS,),
    commit_strategy=CommitStrategy.NONE,
)
