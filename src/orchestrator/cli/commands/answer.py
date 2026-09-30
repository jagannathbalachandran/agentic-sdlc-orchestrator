"""`orchestrator answer` command: answer a Clarification checkpoint and continue."""

from __future__ import annotations

import argparse
from pathlib import Path

from orchestrator.cli.commands._common import (
    build_reliability_limits,
    describe,
    executor_for,
    max_run_duration_seconds,
    policies_for,
    push_if_completed,
    record_run,
)
from orchestrator.engine.fsm import DriveRequest, RunRef, drive, resolve_checkpoint
from orchestrator.models.approvals import ApprovalDecision

COMMAND_NAME = "answer"


def add_subparser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """Register `answer` on the top-level CLI parser."""
    parser = subparsers.add_parser(
        COMMAND_NAME, help="Answer a Clarification checkpoint and continue."
    )
    parser.add_argument("project", help="Registered project name")
    parser.add_argument("run_id", help="Run id to answer")
    parser.add_argument("--comment", required=True, help="The answer text")
    parser.add_argument("--approver", default="operator", help="Who answered")


def handle(args: argparse.Namespace, orch_home: Path) -> int:
    """Run the answer command; returns the process exit code."""
    ref = RunRef(orch_home, args.project, args.run_id)
    duration = max_run_duration_seconds()
    graph_state = resolve_checkpoint(
        ref, ApprovalDecision.ANSWER, args.comment, args.approver, duration
    )
    result = drive(
        DriveRequest(
            orch_home,
            args.project,
            args.run_id,
            graph_state.scenario_id,
            target_repo_url=graph_state.target_repo_url,
            executor_kind=graph_state.executor_kind,
        ),
        executor=executor_for(graph_state.executor_kind),
        max_run_duration_seconds=duration,
        policies=policies_for(graph_state.target_repo_url),
        reliability=build_reliability_limits(),
    )
    push_result = push_if_completed(ref, result.graph_state)
    record_run(orch_home, args.project, result.graph_state, args.approver, push_result)
    print(describe(result.graph_state))
    return 0
