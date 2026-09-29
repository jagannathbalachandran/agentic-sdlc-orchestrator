"""S1 Requirements — StageSpec binding (requirements.md §7).

Clarification is conditional on blocking questions in the real design; that
detection needs real agent output (T4), so no checkpoint is wired here yet —
this stage always proceeds straight to S2.
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
