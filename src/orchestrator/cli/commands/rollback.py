"""`orchestrator rollback` command: reset the workspace to the last recorded
checkpoint commit (T7.1, G-14) — a manual recovery action for a human who has
decided the workspace is beyond fixing forward. Discards uncommitted work and
any commits after the checkpoint; does not change the run's terminal/
checkpoint state.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from orchestrator.cli.commands._common import max_run_duration_seconds
from orchestrator.engine.fsm import RunRef, rollback_to_checkpoint

COMMAND_NAME = "rollback"


def add_subparser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """Register `rollback` on the top-level CLI parser."""
    parser = subparsers.add_parser(
        COMMAND_NAME, help="Reset the workspace to the last recorded checkpoint."
    )
    parser.add_argument("project", help="Registered project name")
    parser.add_argument("run_id", help="Run id to roll back")


def handle(args: argparse.Namespace, orch_home: Path) -> int:
    """Run the rollback command; returns the process exit code."""
    graph_state = rollback_to_checkpoint(
        RunRef(orch_home, args.project, args.run_id), max_run_duration_seconds()
    )
    print(f"run {args.run_id}: rolled back to {graph_state.last_checkpoint_commit}")
    return 0
