"""S5a Implement + unit tests — StageSpec binding (requirements.md §7).

Depends on S4 directly, same as S5b — the two run concurrently via
engine/scheduler.py's threaded batch runner (T6.1), joined before S6.
"""

from __future__ import annotations

from orchestrator.models.graph import CommitStrategy, StageId, StageSpec

SPEC = StageSpec(
    stage_id=StageId.S5A_IMPLEMENT,
    owner_profile="developer",
    depends_on=(StageId.S4_PLAN,),
    allowed_write_paths=("src/**", "tests/unit/**"),
    commit_strategy=CommitStrategy.ONE_PER_TASK,
)
