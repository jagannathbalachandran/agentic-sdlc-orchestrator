"""`orchestrator reject` command: reject the pending checkpoint, with feedback."""

from __future__ import annotations

import argparse
from pathlib import Path

from orchestrator.cli.commands._common import (
    FIXTURES_ROOT,
    describe,
    max_run_duration_seconds,
)
from orchestrator.engine.fsm import DriveRequest, RunRef, drive, resolve_checkpoint
from orchestrator.executors.mock import MockExecutor
from orchestrator.models.approvals import ApprovalDecision
from orchestrator.policies.registry import build_default_policies

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
        print(describe(graph_state))
        return 0
    result = drive(
        DriveRequest(orch_home, args.project, args.run_id, graph_state.scenario_id),
        executor=MockExecutor(FIXTURES_ROOT),
        max_run_duration_seconds=duration,
        policies=build_default_policies(),
    )
    print(describe(result.graph_state))
    return 0
