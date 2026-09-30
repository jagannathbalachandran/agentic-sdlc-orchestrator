"""Tests for orchestrator.engine.runner (T2.1 walking-skeleton proof)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from orchestrator.audit.event_log import EventLog
from orchestrator.engine.graph import GRAPH
from orchestrator.engine.runner import (
    CommitTrailerContext,
    StageGateFailure,
    StageGates,
    StageRunner,
    StageRunnerOptions,
    StageRunRequest,
    commit_message_with_trailers,
    stage_commit_hook,
)
from orchestrator.executors.mock import MockExecutor
from orchestrator.gates.base import StageContext
from orchestrator.models.graph import (
    CommitStrategy,
    GateOutcome,
    StageId,
    StageSpec,
    StageStatus,
)
from orchestrator.workspace.git_ops import init_repo, run_git

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
    # S0's real spec is requires_agent=False (engine/fsm.py's own S0 commit
    # hook does the real workspace prep + 00-source.md write, exercised in
    # tests/unit/engine/test_fsm.py) — this test, using StageRunner directly
    # with no fsm.py-level commit hook, only proves the two-stage sequencing
    # and event ordering below.
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
        options=StageRunnerOptions(gates=StageGates(entry=(_AlwaysFailGate(),))),
    )

    with pytest.raises(StageGateFailure):
        runner.run(_request(StageId.S1_REQUIREMENTS, workspace, "derive FRs"))

    assert not (workspace / "01-requirements.md").exists()
    events = _read_events(events_path)
    # item 3/T9.7: a gate failure now still records stage_finished (not just
    # gate_result) — a failed stage must be diagnosable from events alone.
    assert [event["event_type"] for event in events] == [
        "stage_started",
        "gate_result",
        "stage_finished",
    ]
    gate_payload = events[1]["payload"]
    assert isinstance(gate_payload, dict)
    assert gate_payload["passed"] is False
    finished_payload = events[2]["payload"]
    assert isinstance(finished_payload, dict)
    assert finished_payload["status"] == "failed"
    assert finished_payload["outcome"] == "gate_failure"
    assert "nope" in finished_payload["error"]


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
        options=StageRunnerOptions(commit_hook=_commit_hook),
    )
    result = runner.run(_request(StageId.S1_REQUIREMENTS, workspace, "derive FRs"))

    assert result.commit == "deadbeef"
    assert calls == [StageId.S1_REQUIREMENTS]


def test_commit_message_with_trailers_includes_run_and_stage_always() -> None:
    message = commit_message_with_trailers(
        "S1: stage complete",
        CommitTrailerContext(run_id="demo-20260101-001", stage_label="S1"),
    )
    assert message == ("S1: stage complete\n\nRun: demo-20260101-001\nStage: S1")


def test_commit_message_with_trailers_includes_task_fr_req_when_known() -> None:
    message = commit_message_with_trailers(
        "S5a: implement",
        CommitTrailerContext(
            run_id="demo-20260101-001",
            stage_label="S5a",
            task_id="T-1.1",
            fr_id="FR-1",
            req_id="REQ-1",
        ),
    )
    assert message == (
        "S5a: implement\n\nTask: T-1.1\nFR: FR-1\nReq: REQ-1\n"
        "Run: demo-20260101-001\nStage: S5a"
    )


def test_stage_commit_hook_produces_a_real_commit_with_run_and_stage_trailers(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    init_repo(workspace)
    (workspace / "01-requirements.md").write_text("# FR-1\n", encoding="utf-8")
    context = StageContext(
        run_id="demo-20260101-001",
        stage_id=StageId.S1_REQUIREMENTS,
        attempt=1,
        workspace_path=workspace,
    )
    spec = StageSpec(
        stage_id=StageId.S1_REQUIREMENTS, commit_strategy=CommitStrategy.ONE
    )

    sha = stage_commit_hook(context, spec)

    assert sha is not None
    trailers = run_git(workspace, "log", "-1", "--format=%(trailers)")
    assert "Run: demo-20260101-001" in trailers
    assert "Stage: S1" in trailers


def test_stage_runner_writes_a_transcript_when_transcripts_dir_is_configured(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    transcripts_dir = tmp_path / "agents"
    runner = StageRunner(
        executor=MockExecutor(FIXTURES_ROOT),
        event_log=EventLog(tmp_path / "events.jsonl"),
        clock=_clock,
        options=StageRunnerOptions(transcripts_dir=transcripts_dir),
    )

    runner.run(_request(StageId.S1_REQUIREMENTS, workspace, "derive FRs"))

    payload = json.loads((transcripts_dir / "S1-1.json").read_text(encoding="utf-8"))
    assert payload["stage"] == "S1"
    assert payload["attempt"] == 1
    assert payload["prompt"] == "derive FRs"
    assert payload["response"]["outcome"] == "success"


def test_stage_runner_writes_no_transcript_when_transcripts_dir_is_not_configured(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    runner = StageRunner(
        executor=MockExecutor(FIXTURES_ROOT),
        event_log=EventLog(tmp_path / "events.jsonl"),
        clock=_clock,
    )

    runner.run(_request(StageId.S1_REQUIREMENTS, workspace, "derive FRs"))

    assert not (tmp_path / "agents").exists()


def test_stage_runner_resolves_profile_version_hash_from_profiles_root(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    profiles_root = tmp_path / "profiles"
    profiles_root.mkdir()
    (profiles_root / "analyst.toml").write_text(
        'name = "analyst"\n'
        'persona = "a terse analyst"\n'
        'responsibilities = "derive FRs"\n'
        'output_contract = "01-requirements.md"\n',
        encoding="utf-8",
    )
    transcripts_dir = tmp_path / "agents"
    runner = StageRunner(
        executor=MockExecutor(FIXTURES_ROOT),
        event_log=EventLog(tmp_path / "events.jsonl"),
        clock=_clock,
        options=StageRunnerOptions(
            profiles_root=profiles_root, transcripts_dir=transcripts_dir
        ),
    )

    runner.run(_request(StageId.S1_REQUIREMENTS, workspace, "derive FRs"))

    payload = json.loads((transcripts_dir / "S1-1.json").read_text(encoding="utf-8"))
    assert payload["profile_version_hash"]


def test_stage_runner_leaves_profile_version_hash_none_when_the_profile_is_missing(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    transcripts_dir = tmp_path / "agents"
    runner = StageRunner(
        executor=MockExecutor(FIXTURES_ROOT),
        event_log=EventLog(tmp_path / "events.jsonl"),
        clock=_clock,
        options=StageRunnerOptions(
            profiles_root=tmp_path / "no-such-profiles-dir",
            transcripts_dir=transcripts_dir,
        ),
    )

    runner.run(_request(StageId.S1_REQUIREMENTS, workspace, "derive FRs"))

    payload = json.loads((transcripts_dir / "S1-1.json").read_text(encoding="utf-8"))
    assert payload["profile_version_hash"] is None


def test_stage_runner_records_a_non_null_agent_call_id_on_events(
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

    runner.run(_request(StageId.S1_REQUIREMENTS, workspace, "derive FRs"))

    events = _read_events(events_path)
    assert all(event["agent_call_id"] == "S1-1" for event in events)


def test_stage_runner_leaves_agent_call_id_none_for_a_stage_that_requires_no_agent(
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

    runner.run(_request(StageId.S0_PREPARE, workspace, "prepare the workspace"))

    events = _read_events(events_path)
    assert all(event["agent_call_id"] is None for event in events)


def test_stage_commit_hook_is_a_no_op_when_commit_strategy_is_none(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    init_repo(workspace)
    context = StageContext(
        run_id="demo-20260101-001",
        stage_id=StageId.S2_CODEBASE_ANALYSIS,
        attempt=1,
        workspace_path=workspace,
    )
    spec = StageSpec(
        stage_id=StageId.S2_CODEBASE_ANALYSIS, commit_strategy=CommitStrategy.NONE
    )

    assert stage_commit_hook(context, spec) is None
