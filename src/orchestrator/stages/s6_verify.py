"""S6 Verify — StageSpec binding (requirements.md §7).

The join point after S5a/S5b's parallel pair (T6.1) — depends on *both*, not
just S5b, so the scheduler never starts S6 while the other sibling branch is
still running.

Change-control approval is conditional on a risky change (migration / new
dependency / protected path / large diff) — that detection needs the diff-size
and dependency-control policies (T6.2), so no checkpoint is wired here yet.
"""

from __future__ import annotations

from orchestrator.models.graph import CommitStrategy, StageId, StageSpec

SPEC = StageSpec(
    stage_id=StageId.S6_VERIFY,
    owner_profile=None,
    depends_on=(StageId.S5A_IMPLEMENT, StageId.S5B_ACCEPTANCE_TESTS),
    commit_strategy=CommitStrategy.NONE,
)
