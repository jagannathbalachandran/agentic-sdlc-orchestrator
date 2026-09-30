"""Tests for orchestrator.gates.traceability_gate (T8.1, C10-AC1)."""

from __future__ import annotations

from pathlib import Path

from orchestrator.gates.base import StageContext
from orchestrator.gates.traceability_gate import (
    DesignCitationGate,
    PlanCitationGate,
    RequirementsCitationGate,
)
from orchestrator.models.graph import StageId

RUN_ID = "demo-20260101-001"


def _context(workspace: Path) -> StageContext:
    return StageContext(
        run_id=RUN_ID,
        stage_id=StageId.S1_REQUIREMENTS,
        attempt=1,
        workspace_path=workspace,
    )


def test_requirements_citation_gate_passes_when_every_fr_cites_a_req(
    tmp_path: Path,
) -> None:
    (tmp_path / "01-requirements.md").write_text(
        "# Requirements\n\n## FR-1\nCites: REQ-1\nbody\n\n## FR-2\nCites: REQ-1\nbody\n",
        encoding="utf-8",
    )
    result = RequirementsCitationGate().check(_context(tmp_path))
    assert result.passed


def test_requirements_citation_gate_fails_when_an_fr_has_no_cites_line(
    tmp_path: Path,
) -> None:
    (tmp_path / "01-requirements.md").write_text(
        "# Requirements\n\n## FR-1\nbody, no citation\n", encoding="utf-8"
    )
    result = RequirementsCitationGate().check(_context(tmp_path))
    assert not result.passed
    assert "FR-1" in result.details


def test_requirements_citation_gate_fails_when_the_file_is_missing(
    tmp_path: Path,
) -> None:
    result = RequirementsCitationGate().check(_context(tmp_path))
    assert not result.passed
    assert "01-requirements.md" in result.details


def test_design_citation_gate_passes_when_every_dd_cites_a_fr(tmp_path: Path) -> None:
    (tmp_path / "02-design.md").write_text(
        "# Design\n\n## DD-1\nCites: FR-1, FR-2\nbody\n", encoding="utf-8"
    )
    result = DesignCitationGate().check(_context(tmp_path))
    assert result.passed


def test_design_citation_gate_fails_when_a_dd_has_no_cites_line(tmp_path: Path) -> None:
    (tmp_path / "02-design.md").write_text(
        "# Design\n\n## DD-1\nbody\n", encoding="utf-8"
    )
    result = DesignCitationGate().check(_context(tmp_path))
    assert not result.passed
    assert "DD-1" in result.details


def test_plan_citation_gate_passes_when_every_fr_section_has_a_task_citing_a_dd(
    tmp_path: Path,
) -> None:
    (tmp_path / "03-plan.md").write_text(
        "# Plan\n\n## FR-1\n- T-1.1 (DD-1): does the thing.\n", encoding="utf-8"
    )
    result = PlanCitationGate().check(_context(tmp_path))
    assert result.passed


def test_plan_citation_gate_fails_when_an_fr_section_has_no_task(
    tmp_path: Path,
) -> None:
    (tmp_path / "03-plan.md").write_text(
        "# Plan\n\n## FR-1\nNo tasks listed here.\n", encoding="utf-8"
    )
    result = PlanCitationGate().check(_context(tmp_path))
    assert not result.passed
    assert "FR-1" in result.details


def test_plan_citation_gate_fails_when_there_are_no_fr_sections_at_all(
    tmp_path: Path,
) -> None:
    (tmp_path / "03-plan.md").write_text("# Plan\n\nnothing here\n", encoding="utf-8")
    result = PlanCitationGate().check(_context(tmp_path))
    assert not result.passed
