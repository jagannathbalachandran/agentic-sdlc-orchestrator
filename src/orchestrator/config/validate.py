"""Pre-run validation: schema errors and project registration (C1-AC1, C2-AC3).

`ProjectLookup` is an injected abstraction over "is this project registered" so this
module doesn't depend on the file-backed registry (registry.py, T2.2) — tests use a
stub; the CLI wiring (T2.3) supplies the real, registry-backed lookup.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from orchestrator.config.loader import (
    load_defaults_config,
    load_project_config,
    load_scenario_config,
)
from orchestrator.exceptions import ProjectNotRegisteredError

ProjectLookup = Callable[[str], str | None]


def validate_run_prerequisites(
    project_name: str,
    defaults_path: Path,
    project_config_path: Path,
    scenario_config_path: Path,
    lookup_project: ProjectLookup,
) -> None:
    """Raise if the project is unregistered or any config file is invalid.

    Raises ProjectNotRegisteredError or ConfigValidationError; raises nothing if
    every prerequisite holds.
    """
    if lookup_project(project_name) is None:
        raise ProjectNotRegisteredError(project_name)
    load_defaults_config(defaults_path)
    load_project_config(project_config_path)
    load_scenario_config(scenario_config_path)
