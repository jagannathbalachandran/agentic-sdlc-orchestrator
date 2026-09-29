"""S5b Acceptance tests — StageSpec binding (requirements.md §7).

Depends on S4 directly, same as S5a — the two run concurrently via
engine/scheduler.py's threaded batch runner (T6.1), joined before S6.
"""

from __future__ import annotations

from orchestrator.models.graph import CommitStrategy, StageId, StageSpec

SPEC = StageSpec(
    stage_id=StageId.S5B_ACCEPTANCE_TESTS,
    owner_profile="test_engineer",
    depends_on=(StageId.S4_PLAN,),
    allowed_write_paths=("tests/acceptance/**",),
    commit_strategy=CommitStrategy.ONE,
)
