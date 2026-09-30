"""`orchestrator run` command: start (or, given --run-id, continue) a run.

C1: the real executor is the default; `--mock` opts into the mock one
(tests/CI/demos). `--run-id` is primarily an internal/testing affordance —
it's the same primitive approve/reject/answer reuse to resume a paused run,
reusing whichever executor/target that run already started with.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path

from orchestrator.cli.commands._common import (
    build_new_run_request,
    build_reliability_limits,
    describe,
    executor_for,
    max_run_duration_seconds,
    policies_for,
    push_if_completed,
    record_run,
)
from orchestrator.engine.fsm import (
    DriveRequest,
    RunRef,
    drive,
    generate_run_id,
    load_graph_state,
)
from orchestrator.exceptions import RunRecordError
from orchestrator.models.run import ExecutorKind

COMMAND_NAME = "run"


def add_subparser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """Register `run` on the top-level CLI parser."""
    parser = subparsers.add_parser(COMMAND_NAME, help="Start or continue a run.")
    parser.add_argument("project", help="Registered project name")
    parser.add_argument("scenario_id", help="Scenario id")
    parser.add_argument(
        "--mock", action="store_true", help="Use the mock executor instead of --real"
    )
    parser.add_argument("--operator", default="operator", help="Who started this run")
    parser.add_argument(
        "--run-id",
        default=None,
        help="Continue this existing run instead of starting a new one",
    )


def _build_request(
    args: argparse.Namespace, orch_home: Path, run_id: str
) -> DriveRequest:
    """A resumed `--run-id` reuses the executor/target its run already
    started with (a `RunRecordError` here means it's actually a fresh
    run-id, never driven before). `--mock` stays a self-contained mode that
    needs no registered target at all — C15-AC1's "tests run entirely on the
    mock executor" — resolving one is only for the real, default path.
    """
    try:
        graph_state = load_graph_state(RunRef(orch_home, args.project, run_id))
    except RunRecordError:
        if args.mock:
            return DriveRequest(
                orch_home,
                args.project,
                run_id,
                args.scenario_id,
                executor_kind=ExecutorKind.MOCK,
            )
        return build_new_run_request(
            orch_home, args.project, run_id, args.scenario_id, ExecutorKind.REAL
        )
    return DriveRequest(
        orch_home,
        args.project,
        run_id,
        graph_state.scenario_id,
        target_repo_url=graph_state.target_repo_url,
        executor_kind=graph_state.executor_kind,
    )


def handle(args: argparse.Namespace, orch_home: Path) -> int:
    """Run the run command; returns the process exit code."""
    run_id = args.run_id or generate_run_id(
        orch_home, args.project, args.scenario_id, datetime.now(UTC).date()
    )
    request = _build_request(args, orch_home, run_id)
    result = drive(
        request,
        executor=executor_for(request.executor_kind),
        max_run_duration_seconds=max_run_duration_seconds(),
        policies=policies_for(request.target_repo_url),
        reliability=build_reliability_limits(),
    )
    ref = RunRef(orch_home, args.project, run_id)
    push_result = push_if_completed(ref, result.graph_state)
    record_run(orch_home, args.project, result.graph_state, args.operator, push_result)

    if (
        result.graph_state.terminal_state is not None
        or result.graph_state.pending_checkpoint is not None
    ):
        print(describe(result.graph_state))
    elif result.ran_stages:
        stages = ", ".join(stage.value for stage in result.ran_stages)
        print(f"run {run_id}: ran {stages}")
    else:
        print(f"run {run_id}: nothing to do (graph exhausted or no ready stage)")
    print(f"run-id={run_id}")
    return 0
