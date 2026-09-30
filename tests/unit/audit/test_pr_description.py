"""Tests for orchestrator.audit.pr_description (T8.2, C12-AC5)."""

from __future__ import annotations

from orchestrator.audit.pr_description import generate_pr_description
from orchestrator.models.graph import GraphState, StageId, StageResult, StageStatus


def test_generate_pr_description_identifies_the_run_record() -> None:
    graph_state = GraphState(run_id="scenario-20260101-001", scenario_id="scenario")
    description = generate_pr_description(
        graph_state, run_record_location="/orch-home/runs/project/scenario-20260101-001"
    )
    assert "scenario-20260101-001" in description
    assert "/orch-home/runs/project/scenario-20260101-001" in description


def test_generate_pr_description_links_to_audit_repo_when_given() -> None:
    graph_state = GraphState(run_id="run-1", scenario_id="scenario")
    description = generate_pr_description(
        graph_state,
        run_record_location="/runs/run-1",
        audit_repo_url="https://github.com/org/audit-repo/tree/main/run-1",
    )
    assert "https://github.com/org/audit-repo/tree/main/run-1" in description


def test_generate_pr_description_omits_audit_repo_link_when_not_given() -> None:
    graph_state = GraphState(run_id="run-1", scenario_id="scenario")
    description = generate_pr_description(
        graph_state, run_record_location="/runs/run-1"
    )
    assert "Audit repo" not in description


def test_generate_pr_description_lists_commits() -> None:
    graph_state = GraphState(
        run_id="run-1",
        scenario_id="scenario",
        stages={
            StageId.S5A_IMPLEMENT: StageResult(
                stage_id=StageId.S5A_IMPLEMENT,
                status=StageStatus.PASSED,
                commits=("a" * 40, "b" * 40),
            )
        },
    )
    description = generate_pr_description(
        graph_state, run_record_location="/runs/run-1"
    )
    assert "aaaaaaaa" in description
    assert "bbbbbbbb" in description


def test_generate_pr_description_reports_no_commits() -> None:
    graph_state = GraphState(run_id="run-1", scenario_id="scenario")
    description = generate_pr_description(
        graph_state, run_record_location="/runs/run-1"
    )
    assert "None." in description
