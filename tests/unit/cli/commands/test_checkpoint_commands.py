"""Tests for the approve/reject/answer/stop CLI commands.

Uses the same monkeypatched stub graph as tests/unit/engine/test_fsm.py, since
the real GRAPH doesn't wire any checkpoint in until T3.2.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from orchestrator.cli.commands import answer, approve, reject, stop
from orchestrator.engine.fsm import DriveRequest, drive
from orchestrator.executors.mock import MockExecutor
from orchestrator.models.approvals import ApprovalCheckpointKind
from orchestrator.models.graph import StageId, StageSpec

REPO_ROOT = Path(__file__).resolve().parents[4]
FIXTURES_ROOT = REPO_ROOT / "fixtures" / "mock"
SCENARIO_WITH_NO_FIXTURES = "a-scenario-with-no-fixtures"


def _stub_graph() -> dict[StageId, StageSpec]:
    return {
        StageId.S0_PREPARE: StageSpec(
            stage_id=StageId.S0_PREPARE,
            checkpoint_after=ApprovalCheckpointKind.DESIGN,
        ),
        StageId.S1_REQUIREMENTS: StageSpec(
            stage_id=StageId.S1_REQUIREMENTS,
            owner_profile="analyst",
            depends_on=(StageId.S0_PREPARE,),
        ),
    }


def _paused_request(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> DriveRequest:
    monkeypatch.setattr("orchestrator.engine.fsm.GRAPH", _stub_graph())
    request = DriveRequest(
        orch_home=tmp_path,
        project="demo",
        run_id="run-1",
        scenario_id=SCENARIO_WITH_NO_FIXTURES,
    )
    drive(request, executor=MockExecutor(FIXTURES_ROOT), max_run_duration_seconds=3600)
    return request


def test_approve_handle_clears_the_checkpoint_and_continues(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = _paused_request(tmp_path, monkeypatch)
    args = argparse.Namespace(
        project=request.project, run_id=request.run_id, comment="ok", approver="alice"
    )
    exit_code = approve.handle(args, tmp_path)
    assert exit_code == 0


def test_reject_handle_without_final_continues_the_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = _paused_request(tmp_path, monkeypatch)
    args = argparse.Namespace(
        project=request.project,
        run_id=request.run_id,
        comment="needs work",
        approver="alice",
        final=False,
    )
    exit_code = reject.handle(args, tmp_path)
    assert exit_code == 0


def test_reject_handle_with_final_ends_the_run_as_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = _paused_request(tmp_path, monkeypatch)
    args = argparse.Namespace(
        project=request.project,
        run_id=request.run_id,
        comment="abandoning",
        approver="alice",
        final=True,
    )
    exit_code = reject.handle(args, tmp_path)
    assert exit_code == 0


def test_answer_handle_clears_the_checkpoint_and_continues(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = _paused_request(tmp_path, monkeypatch)
    args = argparse.Namespace(
        project=request.project,
        run_id=request.run_id,
        comment="the answer",
        approver="alice",
    )
    exit_code = answer.handle(args, tmp_path)
    assert exit_code == 0


def test_stop_handle_sets_terminal_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = _paused_request(tmp_path, monkeypatch)
    args = argparse.Namespace(
        project=request.project, run_id=request.run_id, reason="safety concern"
    )
    exit_code = stop.handle(args, tmp_path)
    assert exit_code == 0
