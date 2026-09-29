"""Tests for orchestrator.gates.existence_gate."""

from __future__ import annotations

from pathlib import Path

from orchestrator.gates.base import StageContext
from orchestrator.gates.existence_gate import ExistenceGate
from orchestrator.models.graph import StageId


def test_existence_gate_always_passes(tmp_path: Path) -> None:
    context = StageContext(
        run_id="run-1",
        stage_id=StageId.S2_CODEBASE_ANALYSIS,
        attempt=1,
        workspace_path=tmp_path,
    )
    outcome = ExistenceGate().check(context)
    assert outcome.passed is True
    assert outcome.gate_name == "existence"
