"""Tests for orchestrator.models.graph."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from orchestrator.models.approvals import ApprovalCheckpointKind
from orchestrator.models.graph import (
    CommitStrategy,
    GateOutcome,
    GraphState,
    StageId,
    StageResult,
    StageSpec,
    StageStatus,
)
from orchestrator.models.run import RunState


def test_stage_spec_accepts_minimal_valid_input() -> None:
    spec = StageSpec(stage_id=StageId.S1_REQUIREMENTS, depends_on=(StageId.S0_PREPARE,))
    assert spec.commit_strategy is CommitStrategy.NONE
    assert spec.depends_on == (StageId.S0_PREPARE,)


def test_stage_spec_rejects_unknown_stage_id() -> None:
    with pytest.raises(ValidationError):
        StageSpec(stage_id="S99")  # type: ignore[arg-type]


def test_stage_result_defaults_to_pending_with_no_attempts() -> None:
    result = StageResult(stage_id=StageId.S6_VERIFY)
    assert result.status is StageStatus.PENDING
    assert result.attempts == 0
    assert result.commits == ()


def test_graph_state_requires_run_id() -> None:
    with pytest.raises(ValidationError):
        GraphState()  # type: ignore[call-arg]


def test_graph_state_stores_stage_results_keyed_by_stage_id() -> None:
    state = GraphState(
        run_id="shorten-greenfield-20260929-001",
        scenario_id="shorten-greenfield",
        stages={
            StageId.S0_PREPARE: StageResult(
                stage_id=StageId.S0_PREPARE, status=StageStatus.PASSED
            )
        },
    )
    assert state.stages[StageId.S0_PREPARE].status is StageStatus.PASSED


def test_gate_outcome_requires_gate_name_and_passed() -> None:
    outcome = GateOutcome(gate_name="schema", passed=True)
    assert outcome.details == ""


def test_stage_spec_defaults_checkpoint_after_to_none() -> None:
    spec = StageSpec(stage_id=StageId.S0_PREPARE)
    assert spec.checkpoint_after is None


def test_graph_state_defaults_pending_checkpoint_and_terminal_state_to_none() -> None:
    state = GraphState(run_id="run-1", scenario_id="demo")
    assert state.pending_checkpoint is None
    assert state.terminal_state is None


def test_graph_state_can_hold_a_pending_checkpoint_and_a_terminal_state() -> None:
    state = GraphState(
        run_id="run-1",
        scenario_id="demo",
        pending_checkpoint=ApprovalCheckpointKind.RELEASE,
        terminal_state=RunState.STOPPED,
    )
    assert state.pending_checkpoint is ApprovalCheckpointKind.RELEASE
    assert state.terminal_state is RunState.STOPPED
