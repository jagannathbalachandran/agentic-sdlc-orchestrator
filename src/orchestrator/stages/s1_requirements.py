"""S1 Requirements — StageSpec binding (requirements.md §7).

Clarification is conditional on blocking questions (C7) — `checkpoint_after`
stays `None` here, same reasoning as S6's Change-control (T6.2): a dynamic
override, not this static field, sets `pending_checkpoint` after S1's own
output is known (engine/fsm.py's `_record_batch_result`, T7.4).
"""

from __future__ import annotations

from orchestrator.models.graph import CommitStrategy, StageId, StageSpec

SPEC = StageSpec(
    stage_id=StageId.S1_REQUIREMENTS,
    owner_profile="analyst",
    depends_on=(StageId.S0_PREPARE,),
    allowed_write_paths=("01-requirements.md",),
    commit_strategy=CommitStrategy.ONE,
)
