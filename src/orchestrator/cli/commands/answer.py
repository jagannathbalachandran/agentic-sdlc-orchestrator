"""`orchestrator answer` command: answer a Clarification checkpoint and continue."""

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
        DriveRequest(orch_home, args.project, args.run_id, graph_state.scenario_id),
        executor=MockExecutor(FIXTURES_ROOT),
        max_run_duration_seconds=duration,
    )
    print(describe(result.graph_state))
    return 0
