"""TOML config loading (stdlib tomllib) with schema validation (O-3)."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from orchestrator.config.schema import DefaultsConfig, ProjectConfig, ScenarioConfig
from orchestrator.exceptions import ConfigValidationError

ModelT = TypeVar("ModelT", bound=BaseModel)


def _load_toml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ConfigValidationError(str(path), "file not found")
    try:
        with path.open("rb") as handle:
            return tomllib.load(handle)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigValidationError(str(path), f"malformed TOML: {exc}") from exc


def _load_and_validate(path: Path, model: type[ModelT]) -> ModelT:
    data = _load_toml(path)
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        raise ConfigValidationError(str(path), str(exc)) from exc


def load_defaults_config(path: Path) -> DefaultsConfig:
    """Load and validate config/defaults.toml."""
    return _load_and_validate(path, DefaultsConfig)


def load_project_config(path: Path) -> ProjectConfig:
    """Load and validate a target's .orchestrator/project.toml."""
    return _load_and_validate(path, ProjectConfig)


def load_scenario_config(path: Path) -> ScenarioConfig:
    """Load and validate one .orchestrator/scenarios/<scenario>.toml."""
    return _load_and_validate(path, ScenarioConfig)
