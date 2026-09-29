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
from orchestrator.engine.graph import GRAPH
from orchestrator.exceptions import NoPendingApprovalError, RunAlreadyTerminalError
from orchestrator.executors.mock import MockExecutor
from orchestrator.models.approvals import ApprovalCheckpointKind, ApprovalDecision
from orchestrator.models.graph import CommitStrategy, StageId, StageSpec, StageStatus
from orchestrator.models.run import RunState
from orchestrator.policies.schema_change_control import SchemaChangeControlPolicy
from orchestrator.policies.secret_scan import SecretScanPolicy

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
    the real graph (which only checkpoints at Design/Release)."""
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


def _stub_graph_no_checkpoint() -> dict[StageId, StageSpec]:
    """A minimal graph with no checkpoints, to prove drive() loops through
    multiple stages in a single call when nothing pauses it (item 7)."""
    return {
        StageId.S0_PREPARE: StageSpec(stage_id=StageId.S0_PREPARE),
        StageId.S1_REQUIREMENTS: StageSpec(
            stage_id=StageId.S1_REQUIREMENTS,
            owner_profile="analyst",
            depends_on=(StageId.S0_PREPARE,),
        ),
    }


def _stub_graph_s0_then_s6() -> dict[StageId, StageSpec]:
    """S0 (commits) -> S6 (the policy checkpoint), nothing else — isolates
    S6's dynamic-checkpoint mechanism (T6.2) from the rest of the real graph.
    """
    return {
        StageId.S0_PREPARE: StageSpec(
            stage_id=StageId.S0_PREPARE, commit_strategy=CommitStrategy.ONE
        ),
        StageId.S6_VERIFY: StageSpec(
            stage_id=StageId.S6_VERIFY,
            depends_on=(StageId.S0_PREPARE,),
            commit_strategy=CommitStrategy.NONE,
        ),
    }


def _write_fixture(
    fixtures_root: Path, scenario_id: str, stage: str, fixture: dict[str, object]
) -> None:
    scenario_dir = fixtures_root / scenario_id
    scenario_dir.mkdir(parents=True, exist_ok=True)
    (scenario_dir / f"{stage}.json").write_text(json.dumps(fixture), encoding="utf-8")


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


def test_drive_loops_through_multiple_stages_in_one_call_when_nothing_pauses_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Core proof for item 7: one drive() call advances every pending stage it
    can, not just one, when nothing pauses or fails it."""
    monkeypatch.setattr("orchestrator.engine.fsm.GRAPH", _stub_graph_no_checkpoint())
    request = _request(tmp_path)

    result = drive(
        request, executor=MockExecutor(FIXTURES_ROOT), max_run_duration_seconds=3600
    )

    assert result.ran_stages == (StageId.S0_PREPARE, StageId.S1_REQUIREMENTS)
    assert result.graph_state.terminal_state is RunState.COMPLETED


def test_drive_stops_the_loop_when_a_stage_fails_instead_of_retrying(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No bounded-retry loop exists yet (T7.1) — drive() must stop on a stage
    failure rather than re-attempting it forever in a tight loop."""
    monkeypatch.setattr("orchestrator.engine.fsm.GRAPH", _stub_graph_no_checkpoint())
    empty_fixtures_root = tmp_path / "no-fixtures-here"
    request = _request(tmp_path)

    result = drive(
        request,
        executor=MockExecutor(empty_fixtures_root),
        max_run_duration_seconds=3600,
    )

    assert result.ran_stages == (StageId.S0_PREPARE,)
    assert result.graph_state.stages[StageId.S0_PREPARE].status is StageStatus.FAILED
    assert StageId.S1_REQUIREMENTS not in result.graph_state.stages
    assert result.graph_state.terminal_state is None


def test_drive_reloads_state_between_calls_and_continues_past_a_pause(
    tmp_path: Path,
) -> None:
    """The real 9-stage graph: one call loops S0-S3 and pauses at Design; a
    second, separate drive() call (simulating a fresh process) reloads that
    state from disk and continues from S4."""
    executor = MockExecutor(FIXTURES_ROOT)
    request = _request(tmp_path)

    first = drive(request, executor=executor, max_run_duration_seconds=3600)
    assert first.ran_stages == (
        StageId.S0_PREPARE,
        StageId.S1_REQUIREMENTS,
        StageId.S2_CODEBASE_ANALYSIS,
        StageId.S3_DESIGN,
    )
    assert first.graph_state.pending_checkpoint is ApprovalCheckpointKind.DESIGN

    # A fresh drive() call while still paused makes no further progress.
    second = drive(request, executor=executor, max_run_duration_seconds=3600)
    assert second.ran_stages == ()
    assert second.graph_state.pending_checkpoint is ApprovalCheckpointKind.DESIGN


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
    assert first.ran_stages == (StageId.S0_PREPARE,)
    assert first.graph_state.pending_checkpoint is ApprovalCheckpointKind.DESIGN

    second = drive(request, executor=executor, max_run_duration_seconds=3600)
    assert second.ran_stages == ()
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

    # a fresh drive() call (simulating a separate process) now continues with
    # S1 — the stub graph's last stage, so this also completes the run.
    result = drive(request, executor=executor, max_run_duration_seconds=3600)
    assert result.ran_stages == (StageId.S1_REQUIREMENTS,)
    assert result.graph_state.terminal_state is RunState.COMPLETED


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
    assert result.ran_stages == ()
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


def test_end_to_end_real_graph_reaches_completed_through_all_nine_stages(
    tmp_path: Path,
) -> None:
    """T3.2's core DoD, updated for item 7's looping drive(): one call loops
    S0-S3 and pauses at Design; approving it, one more call loops S4-S8 and
    pauses at Release; approving that completes the run. Every stage's
    entry/exit gate is exercised along the way (recorded as gate_result
    events).
    """
    executor = MockExecutor(FIXTURES_ROOT)
    request = _request(tmp_path)

    to_design = drive(request, executor=executor, max_run_duration_seconds=3600)
    assert to_design.ran_stages == (
        StageId.S0_PREPARE,
        StageId.S1_REQUIREMENTS,
        StageId.S2_CODEBASE_ANALYSIS,
        StageId.S3_DESIGN,
    )
    assert to_design.graph_state.pending_checkpoint is ApprovalCheckpointKind.DESIGN

    resolve_checkpoint(request.ref, ApprovalDecision.APPROVE, "approved", "alice", 3600)

    to_release = drive(request, executor=executor, max_run_duration_seconds=3600)
    assert to_release.ran_stages == (
        StageId.S4_PLAN,
        StageId.S5A_IMPLEMENT,
        StageId.S5B_ACCEPTANCE_TESTS,
        StageId.S6_VERIFY,
        StageId.S7A_DOCS,
        StageId.S7B_REVIEW,
        StageId.S8_RELEASE,
    )
    assert to_release.graph_state.pending_checkpoint is ApprovalCheckpointKind.RELEASE

    final_state = resolve_checkpoint(
        request.ref, ApprovalDecision.APPROVE, "approved", "alice", 3600
    )
    assert final_state.terminal_state is RunState.COMPLETED
    assert all(
        result.status is StageStatus.PASSED for result in final_state.stages.values()
    )
    assert len(final_state.stages) == len(GRAPH)

    # A further call is a no-op — the run is already terminal.
    after_completion = drive(request, executor=executor, max_run_duration_seconds=3600)
    assert after_completion.ran_stages == ()

    # Every stage's entry/exit gate was exercised (recorded as gate_result events).
    events = _read_events(run_dir(tmp_path, "demo", "run-1") / "events.jsonl")
    gate_events = [event for event in events if event["event_type"] == "gate_result"]
    schema_gate_hits = [
        event
        for event in gate_events
        if isinstance(event["payload"], dict)
        and event["payload"]["gate_name"] == "schema"
    ]
    # Two SchemaGate checks (entry + exit) per stage, for all nine stages.
    assert len(schema_gate_hits) == len(GRAPH) * 2
    existence_gate_hits = [
        event
        for event in gate_events
        if isinstance(event["payload"], dict)
        and event["payload"]["gate_name"] == "existence"
    ]
    assert len(existence_gate_hits) == 1  # S2's exit gate, exercised once


def test_s6_change_control_policy_violation_sets_pending_checkpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T6.2's DoD: a schema-change-control violation on S6's diff sets
    pending_checkpoint = CHANGE_CONTROL — S6's StageSpec.checkpoint_after stays
    None (the dynamic-checkpoint override, not the static field)."""
    monkeypatch.setattr("orchestrator.engine.fsm.GRAPH", _stub_graph_s0_then_s6())
    fixtures_root = tmp_path / "fixtures"
    _write_fixture(
        fixtures_root,
        "demo-scenario",
        "S0",
        {
            "summary": "wrote a migration",
            "produced_ids": [],
            "files_written": ["migrations/0001_init.py"],
            "files": {"migrations/0001_init.py": "# migration\n"},
        },
    )
    _write_fixture(
        fixtures_root,
        "demo-scenario",
        "S6",
        {"summary": "verified", "produced_ids": [], "files_written": [], "files": {}},
    )
    policy = SchemaChangeControlPolicy(("migrations/*", "*/migrations/*"))
    request = DriveRequest(tmp_path, "demo", "run-1", "demo-scenario")

    result = drive(
        request,
        executor=MockExecutor(fixtures_root),
        max_run_duration_seconds=3600,
        policies=(policy,),
    )

    assert (
        result.graph_state.pending_checkpoint is ApprovalCheckpointKind.CHANGE_CONTROL
    )
    assert result.graph_state.terminal_state is None
    events = _read_events(run_dir(tmp_path, "demo", "run-1") / "events.jsonl")
    policy_events = [e for e in events if e["event_type"] == "policy_result"]
    assert any(
        isinstance(e["payload"], dict)
        and e["payload"]["policy_id"] == "schema_change_control"
        and e["payload"]["outcome"] == "change_control"
        for e in policy_events
    )


def test_s6_with_a_clean_diff_does_not_pause(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The DoD's other half: a clean diff must not trigger the checkpoint."""
    monkeypatch.setattr("orchestrator.engine.fsm.GRAPH", _stub_graph_s0_then_s6())
    fixtures_root = tmp_path / "fixtures"
    _write_fixture(
        fixtures_root,
        "demo-scenario",
        "S0",
        {
            "summary": "wrote ordinary source",
            "produced_ids": [],
            "files_written": ["src/app.py"],
            "files": {"src/app.py": "print('hi')\n"},
        },
    )
    _write_fixture(
        fixtures_root,
        "demo-scenario",
        "S6",
        {"summary": "verified", "produced_ids": [], "files_written": [], "files": {}},
    )
    policy = SchemaChangeControlPolicy(("migrations/*", "*/migrations/*"))
    request = DriveRequest(tmp_path, "demo", "run-1", "demo-scenario")

    result = drive(
        request,
        executor=MockExecutor(fixtures_root),
        max_run_duration_seconds=3600,
        policies=(policy,),
    )

    assert result.graph_state.pending_checkpoint is None
    assert result.graph_state.terminal_state is RunState.COMPLETED


def test_s6_critical_policy_violation_stops_the_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A critical outcome (e.g. secret_scan) ends the run as stopped, not just
    a pause — C9's "critical violation" -> stopped, distinct from Change-control."""
    monkeypatch.setattr("orchestrator.engine.fsm.GRAPH", _stub_graph_s0_then_s6())
    fixtures_root = tmp_path / "fixtures"
    _write_fixture(
        fixtures_root,
        "demo-scenario",
        "S0",
        {
            "summary": "wrote a config with a leaked key",
            "produced_ids": [],
            "files_written": ["src/config.py"],
            "files": {"src/config.py": "AWS_KEY = 'AKIAABCDEFGHIJKLMNOP'\n"},
        },
    )
    _write_fixture(
        fixtures_root,
        "demo-scenario",
        "S6",
        {"summary": "verified", "produced_ids": [], "files_written": [], "files": {}},
    )
    policy = SecretScanPolicy(("AKIA[0-9A-Z]{16}",))
    request = DriveRequest(tmp_path, "demo", "run-1", "demo-scenario")

    result = drive(
        request,
        executor=MockExecutor(fixtures_root),
        max_run_duration_seconds=3600,
        policies=(policy,),
    )

    assert result.graph_state.terminal_state is RunState.STOPPED
    assert result.graph_state.pending_checkpoint is None
    events = _read_events(run_dir(tmp_path, "demo", "run-1") / "events.jsonl")
    assert any(e["event_type"] == "stop" for e in events)
