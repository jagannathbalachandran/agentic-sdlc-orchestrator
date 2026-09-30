"""Tests for orchestrator.gates.traceability_gate (T8.1, C10-AC1; T9.7 item 2
fixes: real `## ID: <title>` headings, and failing rather than passing
vacuously when a gate finds zero of the sections it's supposed to check)."""

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

# The real heading shape a run actually produced (item 2): an ID followed by
# ": <title>", not the bare "## FR-1"/"## DD-1" the gates originally only
# matched.
REAL_REQUIREMENTS_MD = (
    "# Requirements\n\n"
    "## FR-1: Shorten a URL\n"
    "Cites: REQ-1\n"
    "body.\n\n"
    "## FR-2: Redirect to the original URL\n"
    "Cites: REQ-1\n"
    "body.\n\n"
    "## FR-3: 404 for an unknown code\n"
    "Cites: REQ-1\n"
    "body.\n"
)
REAL_DESIGN_MD = (
    "# Design\n\n"
    "## DD-1: URL shortening endpoint\n"
    "Cites: FR-1\n"
    "body.\n\n"
    "## DD-2: Redirect endpoint\n"
    "Cites: FR-2\n"
    "body.\n\n"
    "## DD-3: 404 handling\n"
    "Cites: FR-3\n"
    "body.\n\n"
    "## DD-4: Data model\n"
    "Cites: FR-1, FR-2\n"
    "body.\n"
)


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


def test_requirements_citation_gate_passes_with_real_titled_headings(
    tmp_path: Path,
) -> None:
    """The exact real-run failure (item 2): headings shaped '## FR-1: <title>'
    previously matched zero sections and passed vacuously."""
    (tmp_path / "01-requirements.md").write_text(REAL_REQUIREMENTS_MD, encoding="utf-8")
    result = RequirementsCitationGate().check(_context(tmp_path))
    assert result.passed
    assert "3 FR(s)" in result.details


def test_requirements_citation_gate_fails_when_an_fr_has_no_cites_line(
    tmp_path: Path,
) -> None:
    (tmp_path / "01-requirements.md").write_text(
        "# Requirements\n\n## FR-1\nbody, no citation\n", encoding="utf-8"
    )
    result = RequirementsCitationGate().check(_context(tmp_path))
    assert not result.passed
    assert "FR-1" in result.details


def test_requirements_citation_gate_fails_when_there_are_no_fr_sections_at_all(
    tmp_path: Path,
) -> None:
    """Item 2: zero sections found must fail, not pass vacuously."""
    (tmp_path / "01-requirements.md").write_text(
        "# Requirements\n\nnothing here\n", encoding="utf-8"
    )
    result = RequirementsCitationGate().check(_context(tmp_path))
    assert not result.passed
    assert "no FR sections" in result.details


def test_requirements_citation_gate_fails_when_the_file_is_missing(
    tmp_path: Path,
) -> None:
    result = RequirementsCitationGate().check(_context(tmp_path))
    assert not result.passed
    assert "01-requirements.md" in result.details


def test_design_citation_gate_passes_when_every_dd_cites_a_fr_and_every_fr_is_covered(
    tmp_path: Path,
) -> None:
    (tmp_path / "01-requirements.md").write_text(
        "# Requirements\n\n## FR-1\nCites: REQ-1\nbody\n\n## FR-2\nCites: REQ-1\nbody\n",
        encoding="utf-8",
    )
    (tmp_path / "02-design.md").write_text(
        "# Design\n\n## DD-1\nCites: FR-1, FR-2\nbody\n", encoding="utf-8"
    )
    result = DesignCitationGate().check(_context(tmp_path))
    assert result.passed


def test_design_citation_gate_passes_with_real_titled_headings(tmp_path: Path) -> None:
    """The exact real-run failure (item 2): a design with DD-1..DD-4, each
    with a real 'Cites:' line, reported passed with "0 DD(s) cite an FR"
    because '## DD-1: <title>' matched zero bare '## DD-1' headings."""
    (tmp_path / "01-requirements.md").write_text(REAL_REQUIREMENTS_MD, encoding="utf-8")
    (tmp_path / "02-design.md").write_text(REAL_DESIGN_MD, encoding="utf-8")
    result = DesignCitationGate().check(_context(tmp_path))
    assert result.passed
    assert "4 DD(s)" in result.details
    assert "3 FR(s)" in result.details


def test_design_citation_gate_fails_when_a_dd_has_no_cites_line(tmp_path: Path) -> None:
    (tmp_path / "01-requirements.md").write_text(
        "# Requirements\n\n## FR-1\nCites: REQ-1\nbody\n", encoding="utf-8"
    )
    (tmp_path / "02-design.md").write_text(
        "# Design\n\n## DD-1\nbody\n", encoding="utf-8"
    )
    result = DesignCitationGate().check(_context(tmp_path))
    assert not result.passed
    assert "DD-1" in result.details


def test_design_citation_gate_fails_when_there_are_no_dd_sections_at_all(
    tmp_path: Path,
) -> None:
    """Item 2: zero sections found must fail, not pass vacuously with '0
    DD(s) cite an FR'."""
    (tmp_path / "01-requirements.md").write_text(
        "# Requirements\n\n## FR-1\nCites: REQ-1\nbody\n", encoding="utf-8"
    )
    (tmp_path / "02-design.md").write_text(
        "# Design\n\nnothing here\n", encoding="utf-8"
    )
    result = DesignCitationGate().check(_context(tmp_path))
    assert not result.passed
    assert "no DD sections" in result.details


def test_design_citation_gate_fails_when_an_fr_is_not_covered_by_any_dd(
    tmp_path: Path,
) -> None:
    """S3's own exit condition (§7): "every FR covered by >=1 DD" — the
    reverse direction from "every DD cites >=1 FR", which nothing checked
    before item 2."""
    (tmp_path / "01-requirements.md").write_text(REAL_REQUIREMENTS_MD, encoding="utf-8")
    (tmp_path / "02-design.md").write_text(
        # Only cites FR-1 — FR-2 and FR-3 (both real, both in
        # 01-requirements.md) are never covered by any DD.
        "# Design\n\n## DD-1: URL shortening endpoint\nCites: FR-1\nbody.\n",
        encoding="utf-8",
    )
    result = DesignCitationGate().check(_context(tmp_path))
    assert not result.passed
    assert "FR-2" in result.details
    assert "FR-3" in result.details


def test_design_citation_gate_fails_when_requirements_file_is_missing(
    tmp_path: Path,
) -> None:
    (tmp_path / "02-design.md").write_text(
        "# Design\n\n## DD-1\nCites: FR-1\nbody\n", encoding="utf-8"
    )
    result = DesignCitationGate().check(_context(tmp_path))
    assert not result.passed
    assert "01-requirements.md" in result.details


def test_design_citation_gate_fails_when_the_file_is_missing(tmp_path: Path) -> None:
    result = DesignCitationGate().check(_context(tmp_path))
    assert not result.passed
    assert "02-design.md" in result.details


def test_plan_citation_gate_passes_when_every_fr_section_has_a_task_citing_a_dd(
    tmp_path: Path,
) -> None:
    (tmp_path / "03-plan.md").write_text(
        "# Plan\n\n## FR-1\n- T-1.1 (DD-1): does the thing.\n", encoding="utf-8"
    )
    result = PlanCitationGate().check(_context(tmp_path))
    assert result.passed


def test_plan_citation_gate_passes_with_real_titled_fr_headings(tmp_path: Path) -> None:
    """Item 2: '## FR-1: <title>' headings, same bug as the other two gates."""
    (tmp_path / "03-plan.md").write_text(
        "# Plan\n\n## FR-1: Shorten a URL\n- T-1.1 (DD-1): does the thing.\n",
        encoding="utf-8",
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


def test_plan_citation_gate_uses_the_same_parser_s5a_does(tmp_path: Path) -> None:
    """T9.8: a real run's S4 gate passed a plan whose own (separate, drifted)
    parser then found zero tasks at S5a. `PlanCitationGate` now fails
    whenever `gates.traceability_gate.parse_plan_tasks` -- the exact
    function `engine/plan_tasks.py` wraps for S5a -- finds no tasks, even if
    every other check in this gate somehow missed it.
    """
    from orchestrator.gates.traceability_gate import parse_plan_tasks

    plan_md = "# Plan\n\n## FR-1: Shorten a URL\n- T-1.1 (DD-1): does the thing.\n"
    (tmp_path / "03-plan.md").write_text(plan_md, encoding="utf-8")

    assert parse_plan_tasks(plan_md)  # sanity: the shared parser finds it too
    result = PlanCitationGate().check(_context(tmp_path))
    assert result.passed
