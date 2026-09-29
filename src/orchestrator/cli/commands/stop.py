"""`orchestrator stop` command: halt a run for safety/control, regardless of the
work (D-14)."""

from __future__ import annotations

import argparse
from pathlib import Path

from orchestrator.cli.commands._common import describe, max_run_duration_seconds
from orchestrator.engine.fsm import RunRef, stop_run

COMMAND_NAME = "stop"
DEFAULT_STOP_REASON = "operator requested stop"


def add_subparser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """Register `stop` on the top-level CLI parser."""
    parser = subparsers.add_parser(COMMAND_NAME, help="Halt a run for safety/control.")
    parser.add_argument("project", help="Registered project name")
    parser.add_argument("run_id", help="Run id to stop")
    parser.add_argument(
        "--reason", default=DEFAULT_STOP_REASON, help="Why the run is stopping"
    )


def handle(args: argparse.Namespace, orch_home: Path) -> int:
    """Run the stop command; returns the process exit code."""
    duration = max_run_duration_seconds()
    graph_state = stop_run(
        RunRef(orch_home, args.project, args.run_id), args.reason, duration
    )
    print(describe(graph_state))
    return 0
