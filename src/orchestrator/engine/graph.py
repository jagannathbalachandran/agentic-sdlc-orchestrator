"""The fixed Phase 1 stage graph (requirements.md §7): all nine stages, assembled
from their StageSpec bindings in stages/.

S5a→S5b and S7a→S7b are sequential dependency chains for now (T3.2's "no
parallel yet" scope) — T6.1 makes both members of each pair depend on the same
upstream stage and run concurrently via the scheduler instead.
"""

from __future__ import annotations

from orchestrator.models.graph import StageId, StageSpec
from orchestrator.stages import (
    s0_prepare,
    s1_requirements,
    s2_codebase_analysis,
    s3_design,
    s4_plan,
    s5a_implement,
    s5b_acceptance_tests,
    s6_verify,
    s7a_docs,
    s7b_review,
    s8_release,
)

_STAGE_MODULES = (
    s0_prepare,
    s1_requirements,
    s2_codebase_analysis,
    s3_design,
    s4_plan,
    s5a_implement,
    s5b_acceptance_tests,
    s6_verify,
    s7a_docs,
    s7b_review,
    s8_release,
)

GRAPH: dict[StageId, StageSpec] = {
    module.SPEC.stage_id: module.SPEC for module in _STAGE_MODULES
}


def get_stage_spec(stage_id: StageId) -> StageSpec:
    """Look up one stage's spec. Raises KeyError if not defined in GRAPH."""
    return GRAPH[stage_id]
