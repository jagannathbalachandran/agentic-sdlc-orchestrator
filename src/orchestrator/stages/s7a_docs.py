"""S7a Docs — StageSpec binding (requirements.md §7).

Depends on S6 directly, same as S7b — the two run concurrently via
engine/scheduler.py's threaded batch runner (T6.1), joined before S8.
"""

from __future__ import annotations

from orchestrator.models.graph import CommitStrategy, StageId, StageSpec

SPEC = StageSpec(
    stage_id=StageId.S7A_DOCS,
    owner_profile="technical_writer",
    depends_on=(StageId.S6_VERIFY,),
    allowed_write_paths=("README.md", "docs/**"),
    commit_strategy=CommitStrategy.ONE,
)
