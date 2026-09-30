"""S2 skip-for-greenfield (C4-AC3, requirements.md §12): "S2 skipped with
reason for greenfield; always runs otherwise." `graph_state.base_ref is
None` is what "greenfield" means throughout this codebase (T5.3's own
scenario convention — greenfield.toml has no base_ref; brownfield/ambiguous
both set one).
"""

from __future__ import annotations

import json
from pathlib import Path

from orchestrator.engine.fsm import DriveRequest, drive, run_dir, workspace_dir
from orchestrator.executors.mock import MockExecutor
from orchestrator.models.graph import StageId, StageStatus

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURES_ROOT = REPO_ROOT / "fixtures" / "mock"
SCENARIO_WITH_NO_FIXTURES = "a-scenario-with-no-fixtures"


def _read_events(path: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_greenfield_run_skips_s2_with_a_recorded_reason_and_event(
    tmp_path: Path,
) -> None:
    request = DriveRequest(
        orch_home=tmp_path,
        project="demo",
        run_id="run-1",
        scenario_id=SCENARIO_WITH_NO_FIXTURES,
        base_ref=None,  # greenfield
    )

    result = drive(
        request, executor=MockExecutor(FIXTURES_ROOT), max_run_duration_seconds=3600
    )

    s2 = result.graph_state.stages[StageId.S2_CODEBASE_ANALYSIS]
    assert s2.status is StageStatus.SKIPPED

    events = _read_events(run_dir(tmp_path, "demo", "run-1") / "events.jsonl")
    s2_finished = [
        event
        for event in events
        if event["event_type"] == "stage_finished" and event["stage"] == "S2"
    ]
    assert len(s2_finished) == 1
    payload = s2_finished[0]["payload"]
    assert isinstance(payload, dict)
    assert payload["status"] == "skipped"
    assert "greenfield" in payload["reason"]

    # S3 (depends on S2) still ran — SKIPPED satisfies its dependency.
    assert result.graph_state.stages[StageId.S3_DESIGN].status is StageStatus.PASSED
    workspace = workspace_dir(tmp_path, "demo", "run-1")
    assert not (workspace / "02-impact-analysis.md").exists()


def test_brownfield_run_actually_runs_s2(tmp_path: Path) -> None:
    request = DriveRequest(
        orch_home=tmp_path,
        project="demo",
        run_id="run-1",
        scenario_id=SCENARIO_WITH_NO_FIXTURES,
        base_ref="baseline-greenfield",  # brownfield: a real base_ref
    )

    result = drive(
        request, executor=MockExecutor(FIXTURES_ROOT), max_run_duration_seconds=3600
    )

    s2 = result.graph_state.stages[StageId.S2_CODEBASE_ANALYSIS]
    assert s2.status is StageStatus.PASSED
    assert StageId.S2_CODEBASE_ANALYSIS in result.ran_stages

    events = _read_events(run_dir(tmp_path, "demo", "run-1") / "events.jsonl")
    s2_gate_results = [
        event
        for event in events
        if event["event_type"] == "gate_result" and event["stage"] == "S2"
    ]
    assert s2_gate_results  # S2's real gates ran — not skipped
