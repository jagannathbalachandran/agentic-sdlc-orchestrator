"""Design-rejection re-planning (requirements.md C11): rejecting Design with
feedback re-runs S3 with that feedback, then S4 onward — S1/S2 (everything
upstream of S3) are kept as-is (C11-AC1).

The mechanism is just marking S3 and everything downstream `invalidated`
(C11-AC2) — engine/fsm.py's existing batch-selection machinery already
re-selects any stage that isn't `PASSED`, so no bespoke re-run path is needed;
the re-planned output then passes through the exact same gates/policies/
approvals as a first attempt would (C11-AC3), since nothing about how a stage
runs distinguishes a re-plan from an original run.

Change-control/Release rejection re-planning (G-9's broader extension of this
same idea) stays designed-only this slice — a documented limitation, not this
task's job.
"""

from __future__ import annotations

from orchestrator.engine.graph import GRAPH
from orchestrator.models.graph import GraphState, StageId, StageResult, StageStatus


def _downstream_of(stage_id: StageId) -> set[StageId]:
    """`stage_id` plus every stage that transitively depends on it."""
    downstream = {stage_id}
    changed = True
    while changed:
        changed = False
        for candidate_id, spec in GRAPH.items():
            if candidate_id in downstream:
                continue
            if any(dep in downstream for dep in spec.depends_on):
                downstream.add(candidate_id)
                changed = True
    return downstream


def invalidate_from(graph_state: GraphState, stage_id: StageId) -> tuple[StageId, ...]:
    """Mark `stage_id` and everything downstream of it `invalidated`.

    `stage_id` itself keeps its existing attempt count — its re-run is a real
    next attempt (feedback/an answer changes what it's given, so its mock
    fixture lookup must key off a genuinely later attempt number, not replay
    attempt 1's canned content again). Every stage strictly downstream of it
    has never run in this branch of the re-plan, so those reset to 0.

    Returns the invalidated stage IDs (in `GRAPH`'s order) so the caller can
    record them on the triggering event (C11-AC2: "events record the trigger").
    """
    affected = _downstream_of(stage_id)
    triggering_attempts = graph_state.stages.get(
        stage_id, StageResult(stage_id=stage_id)
    ).attempts
    for candidate_id in affected:
        attempts = triggering_attempts if candidate_id == stage_id else 0
        graph_state.stages[candidate_id] = StageResult(
            stage_id=candidate_id, status=StageStatus.INVALIDATED, attempts=attempts
        )
    return tuple(stage for stage in GRAPH if stage in affected)
