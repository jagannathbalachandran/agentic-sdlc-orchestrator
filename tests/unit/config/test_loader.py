"""Tests for orchestrator.config.loader."""

from __future__ import annotations

from pathlib import Path

import pytest

from orchestrator.config.loader import load_defaults_config, load_project_config
from orchestrator.exceptions import ConfigValidationError

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULTS_TOML = REPO_ROOT / "config" / "defaults.toml"


def test_load_defaults_config_accepts_the_committed_defaults_toml() -> None:
    config = load_defaults_config(DEFAULTS_TOML)
    assert config.coverage_threshold_percent == 85
    assert config.limits.max_agent_calls == 60


def test_load_project_config_accepts_valid_toml(tmp_path: Path) -> None:
    path = tmp_path / "project.toml"
    path.write_text(
        'project_name = "shortener-greenfield-by-agents"\n'
        'approved_dependencies = ["fastapi"]\n',
        encoding="utf-8",
    )
    config = load_project_config(path)
    assert config.project_name == "shortener-greenfield-by-agents"
    assert config.approved_dependencies == ("fastapi",)


def test_load_project_config_rejects_missing_required_field(tmp_path: Path) -> None:
    path = tmp_path / "project.toml"
    path.write_text("approved_dependencies = []\n", encoding="utf-8")
    with pytest.raises(ConfigValidationError):
        load_project_config(path)


def test_load_project_config_rejects_malformed_toml(tmp_path: Path) -> None:
    path = tmp_path / "project.toml"
    path.write_text("this is not [valid toml", encoding="utf-8")
    with pytest.raises(ConfigValidationError):
        load_project_config(path)


def test_load_project_config_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ConfigValidationError):
        load_project_config(tmp_path / "does-not-exist.toml")
