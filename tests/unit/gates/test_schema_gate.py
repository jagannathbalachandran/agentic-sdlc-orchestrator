"""Tests for orchestrator.gates.schema_gate."""

from __future__ import annotations

from pathlib import Path

from orchestrator.gates.base import StageContext
from orchestrator.gates.schema_gate import SchemaGate
from orchestrator.models.graph import StageId


def test_schema_gate_always_passes(tmp_path: Path) -> None:
    context = StageContext(
        run_id="run-1",
        stage_id=StageId.S1_REQUIREMENTS,
        attempt=1,
        workspace_path=tmp_path,
    )
    outcome = SchemaGate().check(context)
    assert outcome.passed is True
    assert outcome.gate_name == "schema"
