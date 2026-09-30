"""`orchestrator reject` command: reject the pending checkpoint, with feedback."""

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

COMMAND_NAME = "reject"


def add_subparser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """Register `reject` on the top-level CLI parser."""
    parser = subparsers.add_parser(COMMAND_NAME, help="Reject the pending checkpoint.")
    parser.add_argument("project", help="Registered project name")
    parser.add_argument("run_id", help="Run id to reject")
    parser.add_argument("--comment", required=True, help="Feedback (required, C7-AC2)")
    parser.add_argument("--approver", default="operator", help="Who rejected")
    parser.add_argument(
        "--final",
        action="store_true",
        help="End the run as rejected, with no re-planning",
    )


def handle(args: argparse.Namespace, orch_home: Path) -> int:
    """Run the reject command; returns the process exit code."""
    ref = RunRef(orch_home, args.project, args.run_id)
    duration = max_run_duration_seconds()
    decision = ApprovalDecision.REJECT_FINAL if args.final else ApprovalDecision.REJECT
    graph_state = resolve_checkpoint(
        ref, decision, args.comment, args.approver, duration
    )
    if args.final:
        record_run(orch_home, args.project, graph_state, args.approver)
        print(describe(graph_state))
        return 0
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
