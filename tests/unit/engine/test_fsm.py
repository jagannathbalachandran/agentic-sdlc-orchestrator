"""Tests for orchestrator.engine.fsm."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from orchestrator.audit.approvals_log import read_approvals
from orchestrator.audit.decisions_log import read_decisions
from orchestrator.audit.run_record import atomic_write_json, read_json
from orchestrator.engine.fsm import (
    DriveRequest,
    ReliabilityLimits,
    RunRef,
    drive,
    generate_run_id,
    resolve_checkpoint,
    rollback_to_checkpoint,
    run_dir,
    stop_run,
    workspace_dir,
)
from orchestrator.engine.graph import GRAPH
from orchestrator.exceptions import (
    NoCheckpointRecordedError,
    NoPendingApprovalError,
    RunAlreadyTerminalError,
)
from orchestrator.executors.mock import MockExecutor
from orchestrator.models.approvals import ApprovalCheckpointKind, ApprovalDecision
from orchestrator.models.graph import (
    CommitStrategy,
    GraphState,
    StageId,
    StageSpec,
    StageStatus,
)
from orchestrator.models.run import RunState
from orchestrator.policies.schema_change_control import SchemaChangeControlPolicy
from orchestrator.policies.secret_scan import SecretScanPolicy
from orchestrator.workspace.git_ops import current_commit

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


def _stub_graph_s5a_then_s6() -> dict[StageId, StageSpec]:
    """S5a (commits, developer) -> S6 — isolates S6's bounded-retry + fix-call
    mechanism (T7.1, G-13) from the rest of the real graph.
    """
    return {
        StageId.S5A_IMPLEMENT: StageSpec(
            stage_id=StageId.S5A_IMPLEMENT,
            owner_profile="developer",
            commit_strategy=CommitStrategy.ONE,
        ),
        StageId.S6_VERIFY: StageSpec(
            stage_id=StageId.S6_VERIFY,
            depends_on=(StageId.S5A_IMPLEMENT,),
            commit_strategy=CommitStrategy.NONE,
        ),
    }


def _stub_graph_s6_s7a_s7b() -> dict[StageId, StageSpec]:
    """S6 -> {S7a, S7b} — isolates S7b's findings-driven bounded retry (T7.1,
    G-15), which invalidates and re-runs all three.
    """
    return {
        StageId.S6_VERIFY: StageSpec(
            stage_id=StageId.S6_VERIFY, commit_strategy=CommitStrategy.NONE
        ),
        StageId.S7A_DOCS: StageSpec(
            stage_id=StageId.S7A_DOCS,
            owner_profile="technical_writer",
            depends_on=(StageId.S6_VERIFY,),
            commit_strategy=CommitStrategy.ONE,
        ),
        StageId.S7B_REVIEW: StageSpec(
            stage_id=StageId.S7B_REVIEW,
            owner_profile="reviewer",
            depends_on=(StageId.S6_VERIFY,),
            commit_strategy=CommitStrategy.NONE,
        ),
    }


def _stub_graph_three_chained_stages() -> dict[StageId, StageSpec]:
    """S0 -> S1 -> S2, all generic-fixture-backed — enough stages that a
    max_agent_calls cap can fire mid-run, before the graph would otherwise
    complete on its own (T7.1 safe-stop).
    """
    return {
        StageId.S0_PREPARE: StageSpec(stage_id=StageId.S0_PREPARE),
        StageId.S1_REQUIREMENTS: StageSpec(
            stage_id=StageId.S1_REQUIREMENTS,
            owner_profile="analyst",
            depends_on=(StageId.S0_PREPARE,),
        ),
        StageId.S2_CODEBASE_ANALYSIS: StageSpec(
            stage_id=StageId.S2_CODEBASE_ANALYSIS,
            owner_profile="analyst",
            depends_on=(StageId.S1_REQUIREMENTS,),
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


def test_drive_retries_a_failing_stage_up_to_its_bounded_limit_then_falls_back_to_human(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T7.1's bounded retry: a generic stage failure (here, no fixture at all
    -> AgentCallOutcome.ERROR) is retried up to invalid_output_max_attempts
    (2, the default) before falling back to human as terminal FAILED with
    full context — not an infinite tight loop, and not an immediate stop."""
    monkeypatch.setattr("orchestrator.engine.fsm.GRAPH", _stub_graph_no_checkpoint())
    empty_fixtures_root = tmp_path / "no-fixtures-here"
    request = _request(tmp_path)

    result = drive(
        request,
        executor=MockExecutor(empty_fixtures_root),
        max_run_duration_seconds=3600,
    )

    assert result.ran_stages == (StageId.S0_PREPARE, StageId.S0_PREPARE)
    assert result.graph_state.stages[StageId.S0_PREPARE].status is StageStatus.FAILED
    assert result.graph_state.stages[StageId.S0_PREPARE].attempts == 2
    assert StageId.S1_REQUIREMENTS not in result.graph_state.stages
    assert result.graph_state.terminal_state is RunState.FAILED
    events = _read_events(run_dir(tmp_path, "demo", "run-1") / "events.jsonl")
    stop_events = [e for e in events if e["event_type"] == "stop"]
    assert len(stop_events) == 1
    assert isinstance(stop_events[0]["payload"], dict)
    assert stop_events[0]["payload"]["attempts"] == 2


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


def test_reject_design_with_feedback_reruns_s3_onward_keeping_s1_s2(
    tmp_path: Path,
) -> None:
    """T7.2/C11: rejecting Design (not --final) invalidates S3 onward, keeping
    S1/S2; a later drive() re-runs S3, which hits its own Design checkpoint
    again (C11-AC3: the re-plan goes through the same approval, not around
    it); approving that re-runs S4 onward for real."""
    executor = MockExecutor(FIXTURES_ROOT)
    request = _request(tmp_path)

    first = drive(request, executor=executor, max_run_duration_seconds=3600)
    assert first.graph_state.pending_checkpoint is ApprovalCheckpointKind.DESIGN

    rejected_state = resolve_checkpoint(
        request.ref, ApprovalDecision.REJECT, "needs more detail", "alice", 3600
    )
    assert rejected_state.pending_checkpoint is None
    assert rejected_state.terminal_state is None
    for stage_id in (
        StageId.S3_DESIGN,
        StageId.S4_PLAN,
        StageId.S5A_IMPLEMENT,
        StageId.S5B_ACCEPTANCE_TESTS,
        StageId.S6_VERIFY,
        StageId.S7A_DOCS,
        StageId.S7B_REVIEW,
        StageId.S8_RELEASE,
    ):
        assert rejected_state.stages[stage_id].status is StageStatus.INVALIDATED
    for stage_id in (
        StageId.S0_PREPARE,
        StageId.S1_REQUIREMENTS,
        StageId.S2_CODEBASE_ANALYSIS,
    ):
        assert rejected_state.stages[stage_id].status is StageStatus.PASSED

    events = _read_events(run_dir(tmp_path, "demo", "run-1") / "events.jsonl")
    retry_events = [e for e in events if e["event_type"] == "retry"]
    assert len(retry_events) == 1
    assert isinstance(retry_events[0]["payload"], dict)
    assert retry_events[0]["payload"]["trigger"] == "design_rejection"
    assert "S3" in retry_events[0]["payload"]["invalidated"]

    second = drive(request, executor=executor, max_run_duration_seconds=3600)
    assert second.ran_stages == (StageId.S3_DESIGN,)
    assert second.graph_state.pending_checkpoint is ApprovalCheckpointKind.DESIGN
    # S3's own attempt count is preserved across invalidation (a re-plan is a
    # real next attempt, not attempt 1 replayed) — its generic mock fixture
    # still resolves via the bare-name fallback regardless of attempt number.
    assert second.graph_state.stages[StageId.S3_DESIGN].attempts == 2

    resolve_checkpoint(
        request.ref, ApprovalDecision.APPROVE, "looks good now", "alice", 3600
    )
    third = drive(request, executor=executor, max_run_duration_seconds=3600)
    assert third.ran_stages == (
        StageId.S4_PLAN,
        StageId.S5A_IMPLEMENT,
        StageId.S5B_ACCEPTANCE_TESTS,
        StageId.S6_VERIFY,
        StageId.S7A_DOCS,
        StageId.S7B_REVIEW,
        StageId.S8_RELEASE,
    )
    assert third.graph_state.pending_checkpoint is ApprovalCheckpointKind.RELEASE


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


def test_s1_blocking_questions_pause_for_clarification_then_answer_reruns_s1(
    tmp_path: Path,
) -> None:
    """T7.4/C7: S1 raising blocking_questions pauses for Clarification (not
    Design/Change-control); answer records the decision in decisions.jsonl
    (C10-AC6) and re-runs S1 (with the answer as context) then downstream
    proceeds normally to the next real checkpoint."""
    fixtures_root = tmp_path / "fixtures"
    _write_fixture(
        fixtures_root,
        "demo-scenario",
        "S0",
        {
            "summary": "prepared",
            "produced_ids": [],
            "files_written": ["00-source.md"],
            "files": {"00-source.md": "req\n"},
        },
    )
    _write_fixture(
        fixtures_root,
        "demo-scenario",
        "S1",
        {
            "summary": "derived FR-1 but need clarification",
            "produced_ids": ["FR-1"],
            "files_written": ["01-requirements.md"],
            "files": {
                "01-requirements.md": "# Requirements\n\n## FR-1\nCites: REQ-1\n"
            },
            "blocking_questions": ["What does 'expire' mean?"],
        },
    )
    _write_fixture(
        fixtures_root,
        "demo-scenario",
        "S1-2",
        {
            "summary": "derived FR-1, clarified",
            "produced_ids": ["FR-1"],
            "files_written": ["01-requirements.md"],
            "files": {
                "01-requirements.md": "# Requirements\n\n## FR-1\nCites: REQ-1\nClarified.\n"
            },
            "blocking_questions": [],
        },
    )
    _write_fixture(
        fixtures_root,
        "demo-scenario",
        "S2",
        {
            "summary": "impact analysis",
            "produced_ids": [],
            "files_written": [],
            "files": {},
        },
    )
    _write_fixture(
        fixtures_root,
        "demo-scenario",
        "S3",
        {
            "summary": "designed",
            "produced_ids": ["DD-1"],
            "files_written": ["02-design.md"],
            "files": {"02-design.md": "# Design\n\n## DD-1\nCites: FR-1\n"},
        },
    )
    request = DriveRequest(tmp_path, "demo", "run-1", "demo-scenario")
    executor = MockExecutor(fixtures_root)

    first = drive(request, executor=executor, max_run_duration_seconds=3600)
    assert first.ran_stages == (StageId.S0_PREPARE, StageId.S1_REQUIREMENTS)
    assert first.graph_state.pending_checkpoint is ApprovalCheckpointKind.CLARIFICATION

    events = _read_events(run_dir(tmp_path, "demo", "run-1") / "events.jsonl")
    requested = [e for e in events if e["event_type"] == "approval_requested"]
    assert isinstance(requested[-1]["payload"], dict)
    assert requested[-1]["payload"]["checkpoint"] == "clarification"
    assert requested[-1]["payload"]["blocking_questions"] == [
        "What does 'expire' mean?"
    ]

    answer_text = "It means a link stops working after 30 days."
    answered = resolve_checkpoint(
        request.ref, ApprovalDecision.ANSWER, answer_text, "alice", 3600
    )
    assert answered.pending_checkpoint is None
    assert answered.clarification_answer == answer_text
    assert answered.stages[StageId.S1_REQUIREMENTS].status is StageStatus.INVALIDATED

    decisions = read_decisions(run_dir(tmp_path, "demo", "run-1") / "decisions.jsonl")
    assert len(decisions) == 1
    assert decisions[0].stage == "S1"
    assert decisions[0].actor == "alice"
    assert decisions[0].choice == answer_text

    second = drive(request, executor=executor, max_run_duration_seconds=3600)
    assert second.ran_stages == (
        StageId.S1_REQUIREMENTS,
        StageId.S2_CODEBASE_ANALYSIS,
        StageId.S3_DESIGN,
    )
    assert second.graph_state.stages[StageId.S1_REQUIREMENTS].attempts == 2
    assert second.graph_state.pending_checkpoint is ApprovalCheckpointKind.DESIGN


def test_s1_with_no_blocking_questions_never_pauses_for_clarification(
    tmp_path: Path,
) -> None:
    request = _request(tmp_path)
    result = drive(
        request, executor=MockExecutor(FIXTURES_ROOT), max_run_duration_seconds=3600
    )
    assert (
        result.graph_state.stages[StageId.S1_REQUIREMENTS].status is StageStatus.PASSED
    )
    assert (
        result.graph_state.pending_checkpoint
        is not ApprovalCheckpointKind.CLARIFICATION
    )


def test_fault_injection_forces_one_s6_failure_then_a_normal_retry_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T7.3/G-16: a scenario flagged for fault injection gets one
    orchestrator-written failing acceptance test forced onto S6's first
    attempt — deterministically demonstrating the S6->S5a retry loop (T7.1)
    rather than depending on a real failure happening to occur. Attempt 2,
    after the fix call, passes normally (no re-injection)."""
    monkeypatch.setattr("orchestrator.engine.fsm.GRAPH", _stub_graph_s5a_then_s6())
    fixtures_root = tmp_path / "fixtures"
    _write_fixture(
        fixtures_root,
        "demo-scenario",
        "S5a",
        {
            "summary": "implemented",
            "produced_ids": [],
            "files_written": ["src/app.py"],
            "files": {"src/app.py": "x = 1\n"},
        },
    )
    _write_fixture(
        fixtures_root,
        "demo-scenario",
        "S5a-2",
        {
            "summary": "fixed",
            "produced_ids": [],
            "files_written": ["src/app.py"],
            "files": {"src/app.py": "x = 2\n"},
        },
    )
    # S6's own fixture would PASS on any attempt if not for the forced
    # override on attempt 1 — proving the injection, not a missing fixture,
    # is what causes the first failure.
    _write_fixture(
        fixtures_root,
        "demo-scenario",
        "S6",
        {"summary": "verified", "produced_ids": [], "files_written": [], "files": {}},
    )
    _write_fixture(
        fixtures_root,
        "demo-scenario",
        "S6-2",
        {"summary": "verified", "produced_ids": [], "files_written": [], "files": {}},
    )
    request = DriveRequest(
        tmp_path, "demo", "run-1", "demo-scenario", inject_fault=True
    )

    result = drive(
        request, executor=MockExecutor(fixtures_root), max_run_duration_seconds=3600
    )

    assert result.graph_state.stages[StageId.S6_VERIFY].status is StageStatus.PASSED
    assert result.graph_state.stages[StageId.S6_VERIFY].attempts == 2
    assert result.graph_state.fault_injected is True

    workspace = workspace_dir(tmp_path, "demo", "run-1")
    assert (workspace / "tests" / "acceptance" / "test_injected_fault.py").is_file()

    events = _read_events(run_dir(tmp_path, "demo", "run-1") / "events.jsonl")
    injected_events = [e for e in events if e["event_type"] == "fault_injected"]
    assert len(injected_events) == 1
    assert injected_events[0]["injected"] is True
    assert isinstance(injected_events[0]["payload"], dict)
    assert (
        injected_events[0]["payload"]["file"]
        == "tests/acceptance/test_injected_fault.py"
    )


def test_s6_failure_gets_a_fix_call_and_passes_on_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T7.1/G-13: S6's first attempt fails (no fixture -> ERROR); a developer
    fix call runs (attempt 2's own fixture); S6's second attempt passes."""
    monkeypatch.setattr("orchestrator.engine.fsm.GRAPH", _stub_graph_s5a_then_s6())
    fixtures_root = tmp_path / "fixtures"
    _write_fixture(
        fixtures_root,
        "demo-scenario",
        "S5a",
        {
            "summary": "implemented",
            "produced_ids": [],
            "files_written": ["src/app.py"],
            "files": {"src/app.py": "x = 1\n"},
        },
    )
    _write_fixture(
        fixtures_root,
        "demo-scenario",
        "S5a-2",
        {
            "summary": "fixed",
            "produced_ids": [],
            "files_written": ["src/app.py"],
            "files": {"src/app.py": "x = 2\n"},
        },
    )
    # No S6/S6-1 fixture at all -> attempt 1 is AgentCallOutcome.ERROR (FAILED).
    _write_fixture(
        fixtures_root,
        "demo-scenario",
        "S6-2",
        {"summary": "verified", "produced_ids": [], "files_written": [], "files": {}},
    )
    request = DriveRequest(tmp_path, "demo", "run-1", "demo-scenario")

    result = drive(
        request, executor=MockExecutor(fixtures_root), max_run_duration_seconds=3600
    )

    assert result.graph_state.stages[StageId.S6_VERIFY].status is StageStatus.PASSED
    assert result.graph_state.stages[StageId.S6_VERIFY].attempts == 2
    assert result.graph_state.terminal_state is RunState.COMPLETED
    assert result.ran_stages.count(StageId.S6_VERIFY) == 2


def test_s6_failure_falls_back_to_human_after_exhausting_its_retries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T7.1's DoD: hitting the bounded-loop max falls back to human with full
    context — terminal FAILED, not a silent stop, with the attempt count and
    reason recorded on the stop event."""
    monkeypatch.setattr("orchestrator.engine.fsm.GRAPH", _stub_graph_s5a_then_s6())
    fixtures_root = tmp_path / "fixtures"
    _write_fixture(
        fixtures_root,
        "demo-scenario",
        "S5a",
        {
            "summary": "implemented",
            "produced_ids": [],
            "files_written": ["src/app.py"],
            "files": {"src/app.py": "x = 1\n"},
        },
    )
    # No S6 fixture, ever (any attempt) -> every attempt is ERROR (FAILED).
    request = DriveRequest(tmp_path, "demo", "run-1", "demo-scenario")

    result = drive(
        request, executor=MockExecutor(fixtures_root), max_run_duration_seconds=3600
    )

    assert result.graph_state.stages[StageId.S6_VERIFY].status is StageStatus.FAILED
    assert result.graph_state.stages[StageId.S6_VERIFY].attempts == 3
    assert result.graph_state.terminal_state is RunState.FAILED
    events = _read_events(run_dir(tmp_path, "demo", "run-1") / "events.jsonl")
    stop_events = [e for e in events if e["event_type"] == "stop"]
    assert len(stop_events) == 1
    assert isinstance(stop_events[0]["payload"], dict)
    assert stop_events[0]["payload"]["attempts"] == 3
    assert "S6" in str(stop_events[0]["payload"]["reason"])


def test_s7b_high_severity_findings_trigger_a_fix_call_and_rerun_s6_s7a_s7b(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T7.1/G-15: S7b passes its own call but reports a high-severity finding
    -> a fix call, then S6/S7a/S7b are all invalidated and re-run (not just
    S7b) -> a clean second S7b pass completes the run."""
    monkeypatch.setattr("orchestrator.engine.fsm.GRAPH", _stub_graph_s6_s7a_s7b())
    fixtures_root = tmp_path / "fixtures"
    _write_fixture(
        fixtures_root,
        "demo-scenario",
        "S6",
        {"summary": "verified", "produced_ids": [], "files_written": [], "files": {}},
    )
    _write_fixture(
        fixtures_root,
        "demo-scenario",
        "S7a",
        {
            "summary": "docs updated",
            "produced_ids": [],
            "files_written": ["README.md"],
            "files": {"README.md": "# docs\n"},
        },
    )
    _write_fixture(
        fixtures_root,
        "demo-scenario",
        "S7b",
        {
            "summary": "found a high severity issue",
            "produced_ids": ["finding-1"],
            "files_written": [],
            "files": {},
            "high_severity_findings": ["finding-1"],
        },
    )
    _write_fixture(
        fixtures_root,
        "demo-scenario",
        "S5a-2",
        {
            "summary": "fixed the finding",
            "produced_ids": [],
            "files_written": ["src/fix.py"],
            "files": {"src/fix.py": "# fix\n"},
        },
    )
    _write_fixture(
        fixtures_root,
        "demo-scenario",
        "S7b-2",
        {
            "summary": "no more issues",
            "produced_ids": [],
            "files_written": [],
            "files": {},
            "high_severity_findings": [],
        },
    )
    request = DriveRequest(tmp_path, "demo", "run-1", "demo-scenario")

    result = drive(
        request, executor=MockExecutor(fixtures_root), max_run_duration_seconds=3600
    )

    assert result.graph_state.terminal_state is RunState.COMPLETED
    assert result.graph_state.stages[StageId.S7B_REVIEW].attempts == 2
    assert result.ran_stages.count(StageId.S6_VERIFY) == 2
    assert result.ran_stages.count(StageId.S7A_DOCS) == 2
    assert result.ran_stages.count(StageId.S7B_REVIEW) == 2


def test_safe_stop_ends_the_run_when_max_agent_calls_is_exceeded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """C9 safe-stop: exceeding max_agent_calls stops the run mid-graph,
    terminal STOPPED, with the trigger recorded — not a retry-exhaustion
    fallback, and not silently ignored."""
    monkeypatch.setattr(
        "orchestrator.engine.fsm.GRAPH", _stub_graph_three_chained_stages()
    )
    request = _request(tmp_path)
    reliability = ReliabilityLimits(max_agent_calls=1)

    result = drive(
        request,
        executor=MockExecutor(FIXTURES_ROOT),
        max_run_duration_seconds=3600,
        reliability=reliability,
    )

    assert result.graph_state.terminal_state is RunState.STOPPED
    assert StageId.S2_CODEBASE_ANALYSIS not in result.graph_state.stages
    events = _read_events(run_dir(tmp_path, "demo", "run-1") / "events.jsonl")
    stop_events = [e for e in events if e["event_type"] == "stop"]
    assert len(stop_events) == 1
    assert isinstance(stop_events[0]["payload"], dict)
    assert "max_agent_calls" in str(stop_events[0]["payload"]["reason"])


def test_rollback_to_checkpoint_resets_the_workspace_to_the_last_recorded_checkpoint(
    tmp_path: Path,
) -> None:
    """T7.1/G-14: rollback discards uncommitted work and any commits made
    after the last recorded checkpoint, landing exactly on that commit."""
    request = _request(tmp_path)
    drive(request, executor=MockExecutor(FIXTURES_ROOT), max_run_duration_seconds=3600)
    workspace = workspace_dir(tmp_path, "demo", "run-1")
    graph_state = read_json(
        run_dir(tmp_path, "demo", "run-1") / "graph.json", GraphState
    )
    checkpoint_commit = graph_state.last_checkpoint_commit
    assert checkpoint_commit is not None

    (workspace / "rogue.txt").write_text("uncommitted junk\n", encoding="utf-8")
    assert (workspace / "rogue.txt").is_file()

    rollback_to_checkpoint(request.ref, 3600)

    assert current_commit(workspace) == checkpoint_commit
    assert not (workspace / "rogue.txt").exists()


def test_rollback_raises_when_no_checkpoint_has_ever_been_recorded(
    tmp_path: Path,
) -> None:
    ref = RunRef(tmp_path, "demo", "run-1")
    atomic_write_json(
        run_dir(tmp_path, "demo", "run-1") / "graph.json",
        GraphState(run_id="run-1", scenario_id="demo-scenario"),
    )

    with pytest.raises(NoCheckpointRecordedError):
        rollback_to_checkpoint(ref, 3600)
