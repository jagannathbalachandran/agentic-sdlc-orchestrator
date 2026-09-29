"""Tests for orchestrator.engine.fsm."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from orchestrator.audit.approvals_log import read_approvals
from orchestrator.engine.fsm import (
    DriveRequest,
    drive,
    generate_run_id,
    resolve_checkpoint,
    run_dir,
    stop_run,
    workspace_dir,
)
from orchestrator.exceptions import NoPendingApprovalError, RunAlreadyTerminalError
from orchestrator.executors.mock import MockExecutor
from orchestrator.models.approvals import ApprovalCheckpointKind, ApprovalDecision
from orchestrator.models.graph import StageId, StageSpec, StageStatus
from orchestrator.models.run import RunState

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURES_ROOT = REPO_ROOT / "fixtures" / "mock"
SCENARIO_WITH_NO_FIXTURES = "a-scenario-with-no-fixtures"


def _request(tmp_path: Path) -> DriveRequest:
    return DriveRequest(
        orch_home=tmp_path,
        project="demo",
        run_id="run-1",
        scenario_id=SCENARIO_WITH_NO_FIXTURES,
    )


def _stub_graph_with_checkpoint_after_s0() -> dict[StageId, StageSpec]:
    """A minimal graph for testing the checkpoint mechanism in isolation from
    the real graph (which doesn't wire any checkpoints in until T3.2)."""
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


def _read_events(path: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_generate_run_id_matches_the_documented_format() -> None:
    run_id = generate_run_id(
        Path("/does/not/exist"), "demo", "shorten-greenfield", date(2026, 9, 29)
    )
    assert run_id == "shorten-greenfield-20260929-001"


def test_generate_run_id_increments_the_sequence_for_existing_runs(
    tmp_path: Path,
) -> None:
    (tmp_path / "runs" / "demo" / "shorten-greenfield-20260929-001").mkdir(parents=True)
    run_id = generate_run_id(tmp_path, "demo", "shorten-greenfield", date(2026, 9, 29))
    assert run_id == "shorten-greenfield-20260929-002"


def test_drive_runs_one_stage_per_call_and_reloads_state_between_calls(
    tmp_path: Path,
) -> None:
    executor = MockExecutor(FIXTURES_ROOT)
    request = _request(tmp_path)

    first = drive(request, executor=executor, max_run_duration_seconds=3600)
    assert first.ran_stage is StageId.S0_PREPARE

    second = drive(request, executor=executor, max_run_duration_seconds=3600)
    assert second.ran_stage is StageId.S1_REQUIREMENTS
    assert second.graph_state.stages[StageId.S0_PREPARE].status is StageStatus.PASSED
    assert (
        second.graph_state.stages[StageId.S1_REQUIREMENTS].status is StageStatus.PASSED
    )

    third = drive(request, executor=executor, max_run_duration_seconds=3600)
    assert third.ran_stage is None


def test_drive_creates_a_fresh_workspace_and_writes_stage_files(tmp_path: Path) -> None:
    drive(
        _request(tmp_path),
        executor=MockExecutor(FIXTURES_ROOT),
        max_run_duration_seconds=3600,
    )
    workspace = workspace_dir(tmp_path, "demo", "run-1")
    assert (workspace / "00-source.md").is_file()


def test_drive_pauses_at_a_checkpoint_and_a_later_call_makes_no_further_progress(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "orchestrator.engine.fsm.GRAPH", _stub_graph_with_checkpoint_after_s0()
    )
    executor = MockExecutor(FIXTURES_ROOT)
    request = _request(tmp_path)

    first = drive(request, executor=executor, max_run_duration_seconds=3600)
    assert first.ran_stage is StageId.S0_PREPARE
    assert first.graph_state.pending_checkpoint is ApprovalCheckpointKind.DESIGN

    second = drive(request, executor=executor, max_run_duration_seconds=3600)
    assert second.ran_stage is None
    assert second.graph_state.pending_checkpoint is ApprovalCheckpointKind.DESIGN
    assert StageId.S1_REQUIREMENTS not in second.graph_state.stages


def test_resolve_checkpoint_approve_clears_pending_records_approval_and_unblocks_drive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "orchestrator.engine.fsm.GRAPH", _stub_graph_with_checkpoint_after_s0()
    )
    executor = MockExecutor(FIXTURES_ROOT)
    request = _request(tmp_path)
    drive(request, executor=executor, max_run_duration_seconds=3600)

    graph_state = resolve_checkpoint(
        request.ref, ApprovalDecision.APPROVE, "looks good", "alice", 3600
    )
    assert graph_state.pending_checkpoint is None

    approvals = read_approvals(run_dir(tmp_path, "demo", "run-1") / "approvals.jsonl")
    assert len(approvals) == 1
    assert approvals[0].decision is ApprovalDecision.APPROVE
    assert approvals[0].comment == "looks good"

    events = _read_events(run_dir(tmp_path, "demo", "run-1") / "events.jsonl")
    assert events[-1]["event_type"] == "approval_recorded"

    # a fresh drive() call (simulating a separate process) now continues with S1
    result = drive(request, executor=executor, max_run_duration_seconds=3600)
    assert result.ran_stage is StageId.S1_REQUIREMENTS


def test_resolve_checkpoint_reject_records_feedback_without_ending_the_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "orchestrator.engine.fsm.GRAPH", _stub_graph_with_checkpoint_after_s0()
    )
    request = _request(tmp_path)
    drive(request, executor=MockExecutor(FIXTURES_ROOT), max_run_duration_seconds=3600)

    graph_state = resolve_checkpoint(
        request.ref, ApprovalDecision.REJECT, "needs more detail", "alice", 3600
    )
    assert graph_state.pending_checkpoint is None
    assert graph_state.terminal_state is None

    approvals = read_approvals(run_dir(tmp_path, "demo", "run-1") / "approvals.jsonl")
    assert approvals[0].decision is ApprovalDecision.REJECT
    assert approvals[0].comment == "needs more detail"


def test_resolve_checkpoint_reject_final_ends_the_run_as_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "orchestrator.engine.fsm.GRAPH", _stub_graph_with_checkpoint_after_s0()
    )
    executor = MockExecutor(FIXTURES_ROOT)
    request = _request(tmp_path)
    drive(request, executor=executor, max_run_duration_seconds=3600)

    graph_state = resolve_checkpoint(
        request.ref, ApprovalDecision.REJECT_FINAL, "abandoning", "alice", 3600
    )
    assert graph_state.terminal_state is RunState.REJECTED

    result = drive(request, executor=executor, max_run_duration_seconds=3600)
    assert result.ran_stage is None
    assert result.graph_state.terminal_state is RunState.REJECTED


def test_resolve_checkpoint_raises_when_nothing_is_pending(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "orchestrator.engine.fsm.GRAPH", _stub_graph_with_checkpoint_after_s0()
    )
    request = _request(tmp_path)
    drive(request, executor=MockExecutor(FIXTURES_ROOT), max_run_duration_seconds=3600)
    resolve_checkpoint(request.ref, ApprovalDecision.APPROVE, "ok", "alice", 3600)

    with pytest.raises(NoPendingApprovalError):
        resolve_checkpoint(
            request.ref, ApprovalDecision.APPROVE, "again", "alice", 3600
        )


def test_stop_run_sets_terminal_state_and_records_an_event(tmp_path: Path) -> None:
    request = _request(tmp_path)
    drive(request, executor=MockExecutor(FIXTURES_ROOT), max_run_duration_seconds=3600)

    graph_state = stop_run(request.ref, "safety concern", 3600)
    assert graph_state.terminal_state is RunState.STOPPED

    events = _read_events(run_dir(tmp_path, "demo", "run-1") / "events.jsonl")
    assert events[-1]["event_type"] == "stop"
    payload = events[-1]["payload"]
    assert isinstance(payload, dict)
    assert payload["reason"] == "safety concern"


def test_stop_run_raises_if_the_run_is_already_terminal(tmp_path: Path) -> None:
    request = _request(tmp_path)
    drive(request, executor=MockExecutor(FIXTURES_ROOT), max_run_duration_seconds=3600)
    stop_run(request.ref, "first stop", 3600)

    with pytest.raises(RunAlreadyTerminalError):
        stop_run(request.ref, "second stop", 3600)
