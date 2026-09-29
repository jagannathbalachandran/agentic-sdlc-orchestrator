"""`orchestrator run` command: start (or, given --run-id, continue) a run.

T2.3/T3.1 scope: --mock only (the real executor is T4); advances pending stages
until it hits a checkpoint, a terminal state, or the graph is exhausted (see
engine/fsm.py's module docstring). --run-id is primarily an internal/testing
affordance right now — it's the same primitive approve/reject/answer reuse to
resume a paused run.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

from orchestrator.cli.commands._common import (
    FIXTURES_ROOT,
    describe,
    max_run_duration_seconds,
)
from orchestrator.engine.fsm import DriveRequest, drive, generate_run_id
from orchestrator.executors.mock import MockExecutor

COMMAND_NAME = "run"


def add_subparser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """Register `run` on the top-level CLI parser."""
    parser = subparsers.add_parser(COMMAND_NAME, help="Start or continue a run.")
    parser.add_argument("project", help="Registered project name")
    parser.add_argument("scenario_id", help="Scenario id")
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Use the mock executor (required until T4 builds the real one)",
    )
    parser.add_argument(
        "--run-id",
        default=None,
        help="Continue this existing run instead of starting a new one",
    )


def handle(args: argparse.Namespace, orch_home: Path) -> int:
    """Run the run command; returns the process exit code."""
    if not args.mock:
        print("real executor not available yet (T4) - pass --mock", file=sys.stderr)
        return 2

    run_id = args.run_id or generate_run_id(
        orch_home, args.project, args.scenario_id, datetime.now(UTC).date()
    )
    result = drive(
        DriveRequest(
            orch_home=orch_home,
            project=args.project,
            run_id=run_id,
            scenario_id=args.scenario_id,
        ),
        executor=MockExecutor(FIXTURES_ROOT),
        max_run_duration_seconds=max_run_duration_seconds(),
    )
    if result.ran_stage is not None:
        print(f"run {run_id}: ran {result.ran_stage.value}")
    elif (
        result.graph_state.pending_checkpoint is None
        and result.graph_state.terminal_state is None
    ):
        print(f"run {run_id}: nothing to do (graph exhausted or no ready stage)")
    else:
        print(describe(result.graph_state))
    print(f"run-id={run_id}")
    return 0
