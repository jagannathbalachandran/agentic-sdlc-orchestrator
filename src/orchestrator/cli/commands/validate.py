"""`orchestrator validate` command: reports schema/registration errors, starts no run.

Kept decoupled from ORCH_HOME/workspace path layout (that's T2.2/T2.3's concern) —
this command takes explicit config file paths.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from orchestrator.config.validate import ProjectLookup, validate_run_prerequisites
from orchestrator.exceptions import ConfigValidationError, ProjectNotRegisteredError

COMMAND_NAME = "validate"


def add_subparser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """Register `validate` on the top-level CLI parser (wired into main.py in T2.3)."""
    parser = subparsers.add_parser(
        COMMAND_NAME, help="Validate project/scenario config before a run."
    )
    parser.add_argument("project", help="Registered project name")
    parser.add_argument(
        "--defaults", required=True, help="Path to config/defaults.toml"
    )
    parser.add_argument("--project-config", required=True, help="Path to project.toml")
    parser.add_argument(
        "--scenario-config", required=True, help="Path to the scenario's toml"
    )


def handle(args: argparse.Namespace, lookup_project: ProjectLookup) -> int:
    """Run the validate command; returns the process exit code."""
    try:
        validate_run_prerequisites(
            project_name=args.project,
            defaults_path=Path(args.defaults),
            project_config_path=Path(args.project_config),
            scenario_config_path=Path(args.scenario_config),
            lookup_project=lookup_project,
        )
    except (ConfigValidationError, ProjectNotRegisteredError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print("OK")
    return 0
