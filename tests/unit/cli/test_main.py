"""Tests for orchestrator.cli.main."""

from __future__ import annotations

from pathlib import Path

import pytest

from orchestrator.cli import main as cli_main

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULTS_TOML = REPO_ROOT / "config" / "defaults.toml"


def test_default_orch_home_uses_env_var_when_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ORCH_HOME", str(tmp_path))
    assert cli_main.default_orch_home() == tmp_path


def test_default_orch_home_falls_back_to_home_dotdir(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ORCH_HOME", raising=False)
    assert cli_main.default_orch_home() == Path.home() / ".orchestrator"


def test_main_dispatches_register_then_validate(tmp_path: Path) -> None:
    project_config = tmp_path / "project.toml"
    project_config.write_text('project_name = "demo"\n', encoding="utf-8")
    scenario_config = tmp_path / "scenario.toml"
    scenario_config.write_text(
        'scenario_id = "demo-scenario"\nreq_id = "REQ-001"\nrequirement_text = "x"\n',
        encoding="utf-8",
    )
    orch_home = tmp_path / "orch-home"

    register_exit = cli_main.main(
        [
            "--orch-home",
            str(orch_home),
            "register",
            "demo",
            "https://example.com/demo.git",
        ]
    )
    assert register_exit == 0

    validate_exit = cli_main.main(
        [
            "--orch-home",
            str(orch_home),
            "validate",
            "demo",
            "--defaults",
            str(DEFAULTS_TOML),
            "--project-config",
            str(project_config),
            "--scenario-config",
            str(scenario_config),
        ]
    )
    assert validate_exit == 0


def test_main_rejects_an_unregistered_project_at_validate(tmp_path: Path) -> None:
    project_config = tmp_path / "project.toml"
    project_config.write_text('project_name = "demo"\n', encoding="utf-8")
    scenario_config = tmp_path / "scenario.toml"
    scenario_config.write_text(
        'scenario_id = "demo-scenario"\nreq_id = "REQ-001"\nrequirement_text = "x"\n',
        encoding="utf-8",
    )
    orch_home = tmp_path / "orch-home"

    validate_exit = cli_main.main(
        [
            "--orch-home",
            str(orch_home),
            "validate",
            "never-registered",
            "--defaults",
            str(DEFAULTS_TOML),
            "--project-config",
            str(project_config),
            "--scenario-config",
            str(scenario_config),
        ]
    )
    assert validate_exit == 1
