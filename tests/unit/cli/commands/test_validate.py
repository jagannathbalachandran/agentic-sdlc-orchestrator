"""Tests for orchestrator.cli.commands.validate."""

from __future__ import annotations

import argparse
from pathlib import Path

from orchestrator.cli.commands import validate as validate_command

REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULTS_TOML = REPO_ROOT / "config" / "defaults.toml"


def _write_valid_project_and_scenario(tmp_path: Path) -> tuple[Path, Path]:
    project_path = tmp_path / "project.toml"
    project_path.write_text('project_name = "demo"\n', encoding="utf-8")
    scenario_path = tmp_path / "scenario.toml"
    scenario_path.write_text(
        'scenario_id = "demo-scenario"\nreq_id = "REQ-001"\nrequirement_text = "x"\n',
        encoding="utf-8",
    )
    return project_path, scenario_path


def test_add_subparser_registers_validate_command() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers()
    validate_command.add_subparser(subparsers)
    args = parser.parse_args(
        [
            "validate",
            "demo",
            "--defaults",
            str(DEFAULTS_TOML),
            "--project-config",
            "project.toml",
            "--scenario-config",
            "scenario.toml",
        ]
    )
    assert args.project == "demo"


def test_handle_returns_zero_for_a_valid_registered_project(tmp_path: Path) -> None:
    project_path, scenario_path = _write_valid_project_and_scenario(tmp_path)
    args = argparse.Namespace(
        project="demo",
        defaults=str(DEFAULTS_TOML),
        project_config=str(project_path),
        scenario_config=str(scenario_path),
    )
    exit_code = validate_command.handle(
        args, lookup_project=lambda _name: "https://example.com/demo.git"
    )
    assert exit_code == 0


def test_handle_returns_one_for_an_unregistered_project(tmp_path: Path) -> None:
    project_path, scenario_path = _write_valid_project_and_scenario(tmp_path)
    args = argparse.Namespace(
        project="demo",
        defaults=str(DEFAULTS_TOML),
        project_config=str(project_path),
        scenario_config=str(scenario_path),
    )
    exit_code = validate_command.handle(args, lookup_project=lambda _name: None)
    assert exit_code == 1
