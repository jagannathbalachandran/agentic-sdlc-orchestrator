"""`orchestrator approve` command: approve the pending checkpoint and continue."""

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

COMMAND_NAME = "approve"


def add_subparser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """Register `approve` on the top-level CLI parser."""
    parser = subparsers.add_parser(
        COMMAND_NAME, help="Approve the pending checkpoint and continue."
    )
    parser.add_argument("project", help="Registered project name")
    parser.add_argument("run_id", help="Run id to approve")
    parser.add_argument("--comment", default="", help="Approval comment")
    parser.add_argument("--approver", default="operator", help="Who approved")


def handle(args: argparse.Namespace, orch_home: Path) -> int:
    """Run the approve command; returns the process exit code."""
    ref = RunRef(orch_home, args.project, args.run_id)
    duration = max_run_duration_seconds()
    graph_state = resolve_checkpoint(
        ref, ApprovalDecision.APPROVE, args.comment, args.approver, duration
    )
    result = drive(
        DriveRequest(orch_home, args.project, args.run_id, graph_state.scenario_id),
        executor=MockExecutor(FIXTURES_ROOT),
        max_run_duration_seconds=duration,
    )
    print(describe(result.graph_state))
    return 0
