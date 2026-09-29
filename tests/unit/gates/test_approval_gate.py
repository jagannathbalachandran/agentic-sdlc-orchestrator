"""Tests for orchestrator.gates.approval_gate."""

from __future__ import annotations

from pathlib import Path

from orchestrator.gates.approval_gate import ApprovalGate
from orchestrator.gates.base import StageContext
from orchestrator.models.approvals import ApprovalCheckpointKind
from orchestrator.models.graph import GraphState, StageId


def _context(tmp_path: Path) -> StageContext:
    return StageContext(
        run_id="run-1", stage_id=StageId.S4_PLAN, attempt=1, workspace_path=tmp_path
    )


def test_approval_gate_passes_when_nothing_is_pending(tmp_path: Path) -> None:
    graph_state = GraphState(run_id="run-1", scenario_id="demo")
    outcome = ApprovalGate(graph_state).check(_context(tmp_path))
    assert outcome.passed is True


def test_approval_gate_fails_when_a_checkpoint_is_pending(tmp_path: Path) -> None:
    graph_state = GraphState(
        run_id="run-1",
        scenario_id="demo",
        pending_checkpoint=ApprovalCheckpointKind.DESIGN,
    )
    outcome = ApprovalGate(graph_state).check(_context(tmp_path))
    assert outcome.passed is False
    assert "design" in outcome.details
