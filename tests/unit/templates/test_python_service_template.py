"""Tests for templates/python-service/ (T5.1, §12 setup, C3-AC2).

Checks structure and config validity fast, in-process. The heavier DoD clause
— "copying the template and running its own CI-equivalent quality gates
locally succeeds on a fresh copy" — needs a real `pip install` into a fresh
venv and is verified manually; recorded in docs/build-notes.md, not here.
"""

from __future__ import annotations

from pathlib import Path

from orchestrator.config.loader import load_project_config

TEMPLATE_ROOT = Path(__file__).resolve().parents[3] / "templates" / "python-service"

EXPECTED_FILES = (
    "pyproject.toml",
    "README.md",
    ".gitignore",
    "scripts/check.py",
    ".github/workflows/ci.yml",
    ".orchestrator/project.toml",
    "src/service/__init__.py",
    "tests/unit/__init__.py",
    "tests/unit/test_smoke.py",
    "tests/acceptance/__init__.py",
)


def test_template_root_exists() -> None:
    assert TEMPLATE_ROOT.is_dir()


def test_template_has_every_expected_scaffold_file() -> None:
    for relative_path in EXPECTED_FILES:
        path = TEMPLATE_ROOT / relative_path
        assert path.is_file(), f"missing {relative_path}"


def test_template_project_toml_validates_against_project_config() -> None:
    config = load_project_config(TEMPLATE_ROOT / ".orchestrator" / "project.toml")
    assert config.project_name == "python-service"
    assert config.approved_dependencies == ()


def test_template_ci_workflow_pins_actions_and_sets_a_job_timeout() -> None:
    workflow_text = (TEMPLATE_ROOT / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8"
    )
    assert "actions/checkout@v4" in workflow_text
    assert "actions/setup-python@v5" in workflow_text
    assert "timeout-minutes:" in workflow_text
    assert "permissions:" in workflow_text


def test_template_check_script_has_the_same_gate_set_as_the_orchestrator() -> None:
    check_text = (TEMPLATE_ROOT / "scripts" / "check.py").read_text(encoding="utf-8")
    for gate in ("ruff check", "ruff format --check", "mypy", "pytest", "pip-audit"):
        assert gate in check_text
