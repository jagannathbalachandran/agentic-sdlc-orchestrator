"""Tests for orchestrator.engine.graph."""

from __future__ import annotations

import pytest

from orchestrator.engine.graph import GRAPH, get_stage_spec
from orchestrator.models.approvals import ApprovalCheckpointKind
from orchestrator.models.graph import StageId


def test_graph_defines_all_nine_stages() -> None:
    assert set(GRAPH.keys()) == set(StageId)


def test_graph_chains_every_stage_to_exactly_one_predecessor_except_s0() -> None:
    assert GRAPH[StageId.S0_PREPARE].depends_on == ()
    assert GRAPH[StageId.S1_REQUIREMENTS].depends_on == (StageId.S0_PREPARE,)
    assert GRAPH[StageId.S2_CODEBASE_ANALYSIS].depends_on == (StageId.S1_REQUIREMENTS,)
    assert GRAPH[StageId.S3_DESIGN].depends_on == (StageId.S2_CODEBASE_ANALYSIS,)
    assert GRAPH[StageId.S4_PLAN].depends_on == (StageId.S3_DESIGN,)
    assert GRAPH[StageId.S5A_IMPLEMENT].depends_on == (StageId.S4_PLAN,)
    assert GRAPH[StageId.S5B_ACCEPTANCE_TESTS].depends_on == (StageId.S5A_IMPLEMENT,)
    assert GRAPH[StageId.S6_VERIFY].depends_on == (StageId.S5B_ACCEPTANCE_TESTS,)
    assert GRAPH[StageId.S7A_DOCS].depends_on == (StageId.S6_VERIFY,)
    assert GRAPH[StageId.S7B_REVIEW].depends_on == (StageId.S7A_DOCS,)
    assert GRAPH[StageId.S8_RELEASE].depends_on == (StageId.S7B_REVIEW,)


def test_only_design_and_release_carry_a_checkpoint() -> None:
    checkpointed = {
        stage_id: spec.checkpoint_after
        for stage_id, spec in GRAPH.items()
        if spec.checkpoint_after is not None
    }
    assert checkpointed == {
        StageId.S3_DESIGN: ApprovalCheckpointKind.DESIGN,
        StageId.S8_RELEASE: ApprovalCheckpointKind.RELEASE,
    }


def test_get_stage_spec_returns_the_matching_spec() -> None:
    assert get_stage_spec(StageId.S6_VERIFY).stage_id is StageId.S6_VERIFY


def test_get_stage_spec_raises_for_an_unknown_stage_id() -> None:
    with pytest.raises(KeyError):
        get_stage_spec("S99")  # type: ignore[arg-type]
