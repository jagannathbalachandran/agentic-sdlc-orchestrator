"""The fixed Phase 1 stage graph (requirements.md §7).

T2.1 defines S0 and S1 only, enough to prove the walking skeleton end to end;
T3.2 extends this to the full S0-S8 graph with every approval checkpoint wired in.
"""

from __future__ import annotations

from orchestrator.models.graph import CommitStrategy, StageId, StageSpec

GRAPH: dict[StageId, StageSpec] = {
    StageId.S0_PREPARE: StageSpec(
        stage_id=StageId.S0_PREPARE,
        depends_on=(),
        commit_strategy=CommitStrategy.ONE,
    ),
    StageId.S1_REQUIREMENTS: StageSpec(
        stage_id=StageId.S1_REQUIREMENTS,
        owner_profile="analyst",
        depends_on=(StageId.S0_PREPARE,),
        commit_strategy=CommitStrategy.ONE,
    ),
}


def get_stage_spec(stage_id: StageId) -> StageSpec:
    """Look up one stage's spec. Raises KeyError if not (yet) defined in GRAPH."""
    return GRAPH[stage_id]
