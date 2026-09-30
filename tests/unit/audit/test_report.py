"""Tests for orchestrator.audit.report (T8.2)."""

from __future__ import annotations

from orchestrator.audit.metrics import Metrics
from orchestrator.audit.report import generate_report
from orchestrator.models.graph import GraphState, StageId, StageResult, StageStatus
from orchestrator.models.run import RunState

METRICS = Metrics(
    run_success=True,
    stage_first_pass_rate=1.0,
    retry_count=0,
    rollback_count=0,
    mttr_seconds=None,
    end_to_end_latency_seconds=42.0,
    human_wait_seconds=0.0,
    end_to_end_latency_excluding_human_wait_seconds=42.0,
    stage_latency_seconds={"S1": 10.0},
    agent_call_latency_seconds={"S1:1": 10.0},
)


def test_generate_report_includes_run_identity_and_outcome() -> None:
    graph_state = GraphState(
        run_id="scenario-20260101-001",
        scenario_id="scenario",
        terminal_state=RunState.COMPLETED,
    )
    report = generate_report(graph_state, METRICS)
    assert "scenario-20260101-001" in report
    assert "completed" in report


def test_generate_report_lists_every_stage_with_status_and_commits() -> None:
    graph_state = GraphState(
        run_id="run-1",
        scenario_id="scenario",
        stages={
            StageId.S1_REQUIREMENTS: StageResult(
                stage_id=StageId.S1_REQUIREMENTS,
                status=StageStatus.PASSED,
                attempts=1,
                commits=("a" * 40,),
            )
        },
    )
    report = generate_report(graph_state, METRICS)
    assert "S1" in report
    assert "passed" in report
    assert "aaaaaaaa" in report


def test_generate_report_shows_in_progress_when_not_terminal() -> None:
    graph_state = GraphState(run_id="run-1", scenario_id="scenario")
    report = generate_report(graph_state, METRICS)
    assert "in progress" in report


def test_generate_report_includes_metrics_section() -> None:
    graph_state = GraphState(run_id="run-1", scenario_id="scenario")
    report = generate_report(graph_state, METRICS)
    assert "## Metrics" in report
    assert "Retry count" in report
    assert "0" in report
