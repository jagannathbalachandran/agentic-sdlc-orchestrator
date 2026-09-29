"""Tests for orchestrator.config.validate."""

from __future__ import annotations

from pathlib import Path

import pytest

from orchestrator.config.validate import validate_run_prerequisites
from orchestrator.exceptions import ConfigValidationError, ProjectNotRegisteredError

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULTS_TOML = REPO_ROOT / "config" / "defaults.toml"


def _write_valid_project_and_scenario(tmp_path: Path) -> tuple[Path, Path]:
    project_path = tmp_path / "project.toml"
    project_path.write_text('project_name = "demo"\n', encoding="utf-8")
    scenario_path = tmp_path / "scenario.toml"
    scenario_path.write_text(
        'scenario_id = "demo-scenario"\n'
        'req_id = "REQ-001"\n'
        'requirement_text = "Shorten, redirect, 404 for unknown codes."\n',
        encoding="utf-8",
    )
    return project_path, scenario_path


def test_validate_run_prerequisites_passes_for_registered_project_with_valid_config(
    tmp_path: Path,
) -> None:
    project_path, scenario_path = _write_valid_project_and_scenario(tmp_path)
    validate_run_prerequisites(
        project_name="demo",
        defaults_path=DEFAULTS_TOML,
        project_config_path=project_path,
        scenario_config_path=scenario_path,
        lookup_project=lambda _name: "https://example.com/demo.git",
    )


def test_validate_run_prerequisites_rejects_unregistered_project(
    tmp_path: Path,
) -> None:
    project_path, scenario_path = _write_valid_project_and_scenario(tmp_path)
    with pytest.raises(ProjectNotRegisteredError):
        validate_run_prerequisites(
            project_name="demo",
            defaults_path=DEFAULTS_TOML,
            project_config_path=project_path,
            scenario_config_path=scenario_path,
            lookup_project=lambda _name: None,
        )


def test_validate_run_prerequisites_rejects_invalid_scenario_config(
    tmp_path: Path,
) -> None:
    project_path, scenario_path = _write_valid_project_and_scenario(tmp_path)
    scenario_path.write_text('scenario_id = "demo-scenario"\n', encoding="utf-8")
    with pytest.raises(ConfigValidationError):
        validate_run_prerequisites(
            project_name="demo",
            defaults_path=DEFAULTS_TOML,
            project_config_path=project_path,
            scenario_config_path=scenario_path,
            lookup_project=lambda _name: "https://example.com/demo.git",
        )
