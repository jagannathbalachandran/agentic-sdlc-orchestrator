"""Tests for orchestrator.engine.fsm."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from orchestrator.engine.fsm import DriveRequest, drive, generate_run_id, workspace_dir
from orchestrator.executors.mock import MockExecutor
from orchestrator.models.graph import StageId, StageStatus

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
