"""S7b Review — StageSpec binding (requirements.md §7).

Depends on S6 directly, same as S7a — the two run concurrently via
engine/scheduler.py's threaded batch runner (T6.1), joined before S8.
"""

from __future__ import annotations

from orchestrator.models.graph import CommitStrategy, StageId, StageSpec

SPEC = StageSpec(
    stage_id=StageId.S7B_REVIEW,
    owner_profile="reviewer",
    depends_on=(StageId.S6_VERIFY,),
    allowed_write_paths=("04-review-findings.md",),
    commit_strategy=CommitStrategy.NONE,
)
