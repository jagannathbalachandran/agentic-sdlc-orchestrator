"""Tests for orchestrator.gates.technology_stack_gate (item 6c, T9.7)."""

from __future__ import annotations

from pathlib import Path

from orchestrator.gates.base import StageContext
from orchestrator.gates.technology_stack_gate import TechnologyStackGate
from orchestrator.models.graph import StageId

DESIGN_WITH_STACK = (
    "# Design\n\n"
    "## Technology stack\n"
    "Python 3.11+, FastAPI, httpx test client. No new dependencies.\n\n"
    "## DD-1\nCites: FR-1\nbody.\n"
)
DESIGN_WITHOUT_STACK = "# Design\n\n## DD-1\nCites: FR-1\nbody.\n"


def _context(tmp_path: Path, attempt: int = 1) -> StageContext:
    return StageContext(
        run_id="run-1",
        stage_id=StageId.S3_DESIGN,
        attempt=attempt,
        workspace_path=tmp_path,
    )


def test_passes_when_a_real_technology_stack_section_is_present(tmp_path: Path) -> None:
    (tmp_path / "02-design.md").write_text(DESIGN_WITH_STACK, encoding="utf-8")
    outcome = TechnologyStackGate().check(_context(tmp_path))
    assert outcome.passed is True


def test_fails_when_the_design_file_is_missing(tmp_path: Path) -> None:
    outcome = TechnologyStackGate().check(_context(tmp_path))
    assert outcome.passed is False
    assert "not found" in outcome.details


def test_fails_when_there_is_no_technology_stack_section_at_all(tmp_path: Path) -> None:
    """The exact real-run failure (item 6): a design with DDs but no stack
    section, no language, no framework, no test client named."""
    (tmp_path / "02-design.md").write_text(DESIGN_WITHOUT_STACK, encoding="utf-8")
    outcome = TechnologyStackGate().check(_context(tmp_path))
    assert outcome.passed is False
    assert "Technology stack" in outcome.details


def test_fails_when_the_technology_stack_section_is_empty(tmp_path: Path) -> None:
    (tmp_path / "02-design.md").write_text(
        "# Design\n\n## Technology stack\n\n## DD-1\nCites: FR-1\nbody.\n",
        encoding="utf-8",
    )
    outcome = TechnologyStackGate().check(_context(tmp_path))
    assert outcome.passed is False
    assert "empty" in outcome.details or "short" in outcome.details


def test_fails_when_the_stack_omits_python_but_the_target_is_a_python_project(
    tmp_path: Path,
) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x"\n', encoding="utf-8"
    )
    (tmp_path / "02-design.md").write_text(
        "# Design\n\n## Technology stack\nSome framework, unspecified language.\n\n"
        "## DD-1\nCites: FR-1\nbody.\n",
        encoding="utf-8",
    )
    outcome = TechnologyStackGate().check(_context(tmp_path))
    assert outcome.passed is False
    assert "Python" in outcome.details


def test_passes_when_the_stack_names_python_and_the_target_is_a_python_project(
    tmp_path: Path,
) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x"\n', encoding="utf-8"
    )
    (tmp_path / "02-design.md").write_text(DESIGN_WITH_STACK, encoding="utf-8")
    outcome = TechnologyStackGate().check(_context(tmp_path))
    assert outcome.passed is True
