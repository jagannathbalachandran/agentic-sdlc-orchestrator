"""Tests for orchestrator.engine.runner (T2.1 walking-skeleton proof)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from orchestrator.audit.event_log import EventLog
from orchestrator.engine.graph import GRAPH
from orchestrator.engine.runner import (
    StageGateFailure,
    StageGates,
    StageRunner,
    StageRunRequest,
)
from orchestrator.executors.mock import MockExecutor
from orchestrator.gates.base import StageContext
from orchestrator.models.graph import GateOutcome, StageId, StageSpec, StageStatus

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURES_ROOT = REPO_ROOT / "fixtures" / "mock"
SCENARIO_WITH_NO_FIXTURES = "a-scenario-with-no-fixtures"


def _clock() -> datetime:
    return datetime(2026, 9, 29, 12, 0, 0, tzinfo=UTC)


def _read_events(path: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _request(stage_id: StageId, workspace: Path, prompt: str) -> StageRunRequest:
    return StageRunRequest(
        spec=GRAPH[stage_id],
        run_id="run-1",
        scenario_id=SCENARIO_WITH_NO_FIXTURES,
        workspace_path=workspace,
        rendered_prompt=prompt,
        timeout_seconds=60,
        budget_usd=0.1,
    )


class _AlwaysFailGate:
    def check(self, _context: StageContext) -> GateOutcome:
        return GateOutcome(gate_name="always-fail", passed=False, details="nope")


def test_stage_runner_drives_s0_then_s1_and_records_events_in_order(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    events_path = tmp_path / "events.jsonl"
    runner = StageRunner(
        executor=MockExecutor(FIXTURES_ROOT),
        event_log=EventLog(events_path),
        clock=_clock,
    )

    s0_result = runner.run(
        _request(StageId.S0_PREPARE, workspace, "prepare the workspace")
    )
    s1_result = runner.run(_request(StageId.S1_REQUIREMENTS, workspace, "derive FRs"))

    assert s0_result.status is StageStatus.PASSED
    assert s1_result.status is StageStatus.PASSED
    assert (workspace / "00-source.md").is_file()
    assert (workspace / "01-requirements.md").is_file()

    events = _read_events(events_path)
    event_shape = [(event["stage"], event["event_type"]) for event in events]
    assert event_shape == [
        ("S0", "stage_started"),
        ("S0", "stage_finished"),
        ("S1", "stage_started"),
        ("S1", "stage_finished"),
    ]


def test_stage_runner_raises_stage_gate_failure_and_never_calls_the_executor(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    events_path = tmp_path / "events.jsonl"
    runner = StageRunner(
        executor=MockExecutor(FIXTURES_ROOT),
        event_log=EventLog(events_path),
        clock=_clock,
        gates=StageGates(entry=(_AlwaysFailGate(),)),
    )

    with pytest.raises(StageGateFailure):
        runner.run(_request(StageId.S1_REQUIREMENTS, workspace, "derive FRs"))

    assert not (workspace / "01-requirements.md").exists()
    events = _read_events(events_path)
    assert [event["event_type"] for event in events] == ["stage_started", "gate_result"]
    payload = events[-1]["payload"]
    assert isinstance(payload, dict)
    assert payload["passed"] is False


def test_stage_runner_invokes_the_commit_hook_only_on_success(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    calls: list[StageId] = []

    def _commit_hook(context: StageContext, _spec: StageSpec) -> str | None:
        calls.append(context.stage_id)
        return "deadbeef"

    runner = StageRunner(
        executor=MockExecutor(FIXTURES_ROOT),
        event_log=EventLog(tmp_path / "events.jsonl"),
        clock=_clock,
        commit_hook=_commit_hook,
    )
    result = runner.run(_request(StageId.S1_REQUIREMENTS, workspace, "derive FRs"))

    assert result.commit == "deadbeef"
    assert calls == [StageId.S1_REQUIREMENTS]
