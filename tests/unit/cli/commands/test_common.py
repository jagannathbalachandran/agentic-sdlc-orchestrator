"""Tests for orchestrator.cli.commands._common — the CLI-layer resolution
`engine/fsm.py` itself deliberately stays independent of (registry lookups,
scenario/project config reads, run.json, push-after-Release).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from orchestrator.cli.commands._common import (
    UnregisteredProjectError,
    build_new_run_request,
    build_reliability_limits,
    policies_for,
    push_if_completed,
    record_run,
    resolve_new_run_inputs,
)
from orchestrator.engine.fsm import RunRef
from orchestrator.exceptions import ConfigValidationError
from orchestrator.models.graph import GraphState
from orchestrator.models.run import ExecutorKind, RunState
from orchestrator.policies.base import FileChange, WorkspaceDiff
from orchestrator.registry import register_project

SCENARIO_TOML = """
scenario_id = "demo-scenario"
req_id = "REQ-1"
requirement_text = "Shorten, redirect, 404 for unknown codes."
base_ref = "baseline-greenfield"
inject_fault = true
"""

PROJECT_TOML = """
project_name = "demo-target"
approved_dependencies = ["fastapi"]
"""


def _target_repo(tmp_path: Path, scenario_id: str = "demo-scenario") -> Path:
    target = tmp_path / "target-repo"
    scenarios_dir = target / ".orchestrator" / "scenarios"
    scenarios_dir.mkdir(parents=True)
    (scenarios_dir / f"{scenario_id}.toml").write_text(SCENARIO_TOML, encoding="utf-8")
    (target / ".orchestrator" / "project.toml").write_text(
        PROJECT_TOML, encoding="utf-8"
    )
    return target


def test_resolve_new_run_inputs_reads_the_targets_own_scenario_config(
    tmp_path: Path,
) -> None:
    orch_home = tmp_path / "orch-home"
    target = _target_repo(tmp_path)
    register_project(orch_home, "demo-project", str(target))

    inputs = resolve_new_run_inputs(orch_home, "demo-project", "demo-scenario")

    assert inputs.target_repo_url == str(target)
    assert inputs.base_ref == "baseline-greenfield"
    assert inputs.req_id == "REQ-1"
    assert inputs.inject_fault is True
    assert "Shorten" in inputs.requirement_text


def test_resolve_new_run_inputs_raises_for_an_unregistered_project(
    tmp_path: Path,
) -> None:
    with pytest.raises(UnregisteredProjectError):
        resolve_new_run_inputs(tmp_path / "orch-home", "never-registered", "s")


def test_resolve_new_run_inputs_raises_for_a_missing_scenario_file(
    tmp_path: Path,
) -> None:
    orch_home = tmp_path / "orch-home"
    target = _target_repo(tmp_path)
    register_project(orch_home, "demo-project", str(target))

    with pytest.raises(ConfigValidationError):
        resolve_new_run_inputs(orch_home, "demo-project", "no-such-scenario")


def test_build_new_run_request_carries_every_resolved_field(tmp_path: Path) -> None:
    orch_home = tmp_path / "orch-home"
    target = _target_repo(tmp_path)
    register_project(orch_home, "demo-project", str(target))

    request = build_new_run_request(
        orch_home, "demo-project", "run-1", "demo-scenario", ExecutorKind.REAL
    )

    assert request.target_repo_url == str(target)
    assert request.base_ref == "baseline-greenfield"
    assert request.req_id == "REQ-1"
    assert request.inject_fault is True
    assert request.executor_kind is ExecutorKind.REAL


def test_policies_for_reads_approved_dependencies_from_the_targets_project_toml(
    tmp_path: Path,
) -> None:
    target = _target_repo(tmp_path)
    policies = policies_for(str(target))
    dependency_control = next(
        p for p in policies if p.policy_id == "dependency_control"
    )
    diff = WorkspaceDiff(
        workspace_path=Path("/unused"),
        base_commit="base",
        head_commit="head",
        current_branch="run/demo",
        files=(
            FileChange(
                path="pyproject.toml",
                added_lines=('    "fastapi>=0.115.0",',),
                removed_lines=(),
            ),
        ),
    )
    # fastapi is on the target's own approved list (PROJECT_TOML above) — no
    # Change-control trigger for it, unlike an unlisted dependency.
    assert dependency_control.check(diff).passed


def test_policies_for_with_no_target_still_returns_all_eight() -> None:
    policies = policies_for(None)
    assert len(policies) == 8


def test_record_run_writes_run_json_with_the_resolved_fields(tmp_path: Path) -> None:
    orch_home = tmp_path / "orch-home"
    graph_state = GraphState(
        run_id="demo-scenario-20260101-001",
        scenario_id="demo-scenario",
        req_id="REQ-1",
        target_repo_url="/some/target",
        base_commit="a" * 40,
        executor_kind=ExecutorKind.REAL,
    )

    record_run(orch_home, "demo-project", graph_state, "jag")

    path = orch_home / "runs" / "demo-project" / graph_state.run_id / "run.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["run_id"] == graph_state.run_id
    assert data["req_id"] == "REQ-1"
    assert data["operator"] == "jag"
    assert data["executor_kind"] == "real"
    assert data["target_url"] == "/some/target"


def test_record_run_skips_when_req_id_is_unknown(tmp_path: Path) -> None:
    orch_home = tmp_path / "orch-home"
    graph_state = GraphState(run_id="run-1", scenario_id="s")

    record_run(orch_home, "demo-project", graph_state, "jag")

    path = orch_home / "runs" / "demo-project" / "run-1" / "run.json"
    assert not path.is_file()


def test_push_if_completed_is_none_when_not_completed(tmp_path: Path) -> None:
    ref = RunRef(tmp_path, "demo-project", "run-1")
    graph_state = GraphState(
        run_id="run-1", scenario_id="s", target_repo_url="/some/target"
    )
    assert push_if_completed(ref, graph_state) is None


def test_build_reliability_limits_reads_per_call_timeout_and_budget_from_config() -> (
    None
):
    """Item 4 of the pre-T10 audit: a real call gets a real per-call budget
    cap and timeout, sourced from config/defaults.toml (not hardcoded)."""
    limits = build_reliability_limits()
    assert limits.per_call_timeout_seconds > 0
    assert limits.budget_usd > 0


def test_push_if_completed_is_none_with_no_real_target(tmp_path: Path) -> None:
    ref = RunRef(tmp_path, "demo-project", "run-1")
    graph_state = GraphState(
        run_id="run-1", scenario_id="s", terminal_state=RunState.COMPLETED
    )
    assert push_if_completed(ref, graph_state) is None
