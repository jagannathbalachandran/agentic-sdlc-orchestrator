"""Tests for orchestrator.gates.base."""

from __future__ import annotations

from pathlib import Path

from orchestrator.gates.base import StageContext
from orchestrator.models.graph import StageId


def test_stage_context_is_frozen_and_holds_the_stage_boundary_fields(
    tmp_path: Path,
) -> None:
    context = StageContext(
        run_id="run-1",
        stage_id=StageId.S1_REQUIREMENTS,
        attempt=1,
        workspace_path=tmp_path,
    )
    assert context.stage_id is StageId.S1_REQUIREMENTS
    assert context.workspace_path == tmp_path
