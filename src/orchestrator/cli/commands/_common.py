"""Shared helpers for CLI commands that touch an existing run.

This is the one place the CLI layer resolves things `drive()`/`engine/fsm.py`
itself deliberately stays independent of — the project registry, scenario/
project config files inside a target repo, and which concrete `Executor` a
run uses (CLAUDE.md: "core engine must not depend on how agents are
executed"). `run.py`/`approve.py`/`reject.py`/`answer.py` all import from
here rather than duplicating this resolution.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import orchestrator
from orchestrator.config.loader import (
    load_defaults_config,
    load_project_config,
    load_scenario_config,
)
from orchestrator.config.schema import ProjectConfig
from orchestrator.engine.fsm import DriveRequest, ReliabilityLimits, RunRef, run_dir
from orchestrator.exceptions import GitCommandError
from orchestrator.executors.base import Executor
from orchestrator.executors.mock import MockExecutor
from orchestrator.executors.real import RealExecutor
from orchestrator.models.graph import GraphState
from orchestrator.models.run import ExecutorKind, RunRecord, RunState
from orchestrator.policies.base import Policy
from orchestrator.policies.registry import build_default_policies
from orchestrator.registry import resolve_project
from orchestrator.workspace.git_ops import current_commit_or_empty_tree, run_git

DEFAULTS_CONFIG_PATH = Path("config/defaults.toml")
FIXTURES_ROOT = Path("fixtures/mock")
PROFILES_ROOT = Path("agents/profiles")
TEMPLATE_PATH = Path("templates/python-service")
SCENARIO_CONFIG_RELATIVE = ".orchestrator/scenarios/{scenario_id}.toml"
PROJECT_CONFIG_RELATIVE = ".orchestrator/project.toml"
RUN_RECORD_FILENAME = "run.json"
SECONDS_PER_MINUTE = 60


def max_run_duration_seconds() -> float:
    """Read the configured run-duration limit and convert it to seconds."""
    defaults = load_defaults_config(DEFAULTS_CONFIG_PATH)
    return defaults.limits.max_run_duration_minutes * SECONDS_PER_MINUTE


def build_reliability_limits() -> ReliabilityLimits:
    """`ReliabilityLimits` from `config/defaults.toml` — retry counts, the
    safe-stop agent-call cap, and the per-call timeout/budget (previously
    hardcoded in engine/fsm.py; now this config's own `limits.per_call_
    timeout_seconds`/`limits.max_call_budget_usd`)."""
    defaults = load_defaults_config(DEFAULTS_CONFIG_PATH)
    return ReliabilityLimits(
        retry_limits=defaults.retry_limits,
        max_agent_calls=defaults.limits.max_agent_calls,
        per_call_timeout_seconds=defaults.limits.per_call_timeout_seconds,
        budget_usd=defaults.limits.max_call_budget_usd,
    )


def executor_for(executor_kind: ExecutorKind) -> Executor:
    """The real thing behind `DriveRequest.executor_kind`/`GraphState.
    executor_kind` — C1's `run` defaults to real, `--mock` selects mock."""
    if executor_kind is ExecutorKind.MOCK:
        return MockExecutor(FIXTURES_ROOT)
    return RealExecutor(PROFILES_ROOT)


def project_config_for(target_repo_url: str) -> ProjectConfig | None:
    """The target's own `.orchestrator/project.toml`, if it has one (a
    workspace not built from a registered target with this file — a stub/
    manual project — simply has no approved-dependency list to enforce)."""
    path = Path(target_repo_url) / PROJECT_CONFIG_RELATIVE
    if not path.is_file():
        return None
    return load_project_config(path)


def policies_for(target_repo_url: str | None) -> tuple[Policy, ...]:
    """The real 8 C6 policies, with `dependency_control`'s approved list
    resolved from the target's own project.toml when one is configured."""
    approved: tuple[str, ...] = ()
    if target_repo_url is not None:
        project_config = project_config_for(target_repo_url)
        if project_config is not None:
            approved = project_config.approved_dependencies
    return build_default_policies(approved)


@dataclass(frozen=True)
class NewRunInputs:
    """Everything resolved for a brand-new run, before its first `drive()`
    call — the registry lookup and scenario-config read `DriveRequest`'s own
    docstring says belongs to the CLI layer, not `engine/fsm.py`."""

    target_repo_url: str
    base_ref: str | None
    requirement_text: str
    req_id: str
    inject_fault: bool


def resolve_new_run_inputs(
    orch_home: Path, project: str, scenario_id: str
) -> NewRunInputs:
    """Resolve `project`'s registered target and `scenario_id`'s own config
    from inside it (`.orchestrator/scenarios/<scenario_id>.toml`, T5.3) —
    raises `ConfigValidationError`/`RunRecordError` if either is missing,
    same as every other config-reading CLI path in this codebase.
    """
    target_repo_url = resolve_project(orch_home, project)
    if target_repo_url is None:
        raise UnregisteredProjectError(project)
    scenario_path = Path(target_repo_url) / SCENARIO_CONFIG_RELATIVE.format(
        scenario_id=scenario_id
    )
    scenario = load_scenario_config(scenario_path)
    return NewRunInputs(
        target_repo_url=target_repo_url,
        base_ref=scenario.base_ref,
        requirement_text=scenario.requirement_text,
        req_id=scenario.req_id,
        inject_fault=scenario.inject_fault,
    )


class UnregisteredProjectError(Exception):
    """Raised when a CLI command names a project `register` was never run for."""

    def __init__(self, project: str) -> None:
        super().__init__(f"project not registered: {project}")
        self.project = project


def build_new_run_request(
    orch_home: Path,
    project: str,
    run_id: str,
    scenario_id: str,
    executor_kind: ExecutorKind,
) -> DriveRequest:
    """The full `DriveRequest` for starting a brand-new run for real — target,
    scenario, and executor all resolved once, here, then persisted onto
    `GraphState` by `drive()`'s own first call."""
    inputs = resolve_new_run_inputs(orch_home, project, scenario_id)
    return DriveRequest(
        orch_home=orch_home,
        project=project,
        run_id=run_id,
        scenario_id=scenario_id,
        inject_fault=inputs.inject_fault,
        target_repo_url=inputs.target_repo_url,
        base_ref=inputs.base_ref,
        requirement_text=inputs.requirement_text,
        req_id=inputs.req_id,
        template_path=str(TEMPLATE_PATH),
        executor_kind=executor_kind,
    )


def describe(graph_state: GraphState) -> str:
    """One-line human-readable status for CLI output."""
    if graph_state.terminal_state is not None:
        return f"run {graph_state.run_id}: {graph_state.terminal_state.value}"
    if graph_state.pending_checkpoint is not None:
        checkpoint = graph_state.pending_checkpoint.value
        return f"run {graph_state.run_id}: awaiting_approval ({checkpoint})"
    return f"run {graph_state.run_id}: running"


def _run_state_for(graph_state: GraphState) -> RunState:
    if graph_state.terminal_state is not None:
        return graph_state.terminal_state
    if graph_state.pending_checkpoint is not None:
        return RunState.AWAITING_APPROVAL
    return RunState.RUNNING


def _effective_config_hash() -> str:
    return hashlib.sha256(DEFAULTS_CONFIG_PATH.read_bytes()).hexdigest()


def record_run(
    orch_home: Path,
    project: str,
    graph_state: GraphState,
    operator: str,
    push_result: str | None = None,
) -> None:
    """Write/update run.json (C1-AC2, §11) from `graph_state`'s current
    values — called after every `drive()`/`resolve_checkpoint()` call that
    might have changed the run's state. Skipped (not a hard failure) when
    `req_id` isn't known yet — a run with no real scenario config behind it
    (a stub/test run) has nothing valid to record.
    """
    if not graph_state.req_id:
        return
    record = RunRecord(
        run_id=graph_state.run_id,
        project=project,
        scenario_id=graph_state.scenario_id,
        req_id=graph_state.req_id,
        operator=operator,
        state=_run_state_for(graph_state),
        started_at=graph_state.started_at or datetime.now(UTC),
        completed_at=datetime.now(UTC)
        if graph_state.terminal_state is not None
        else None,
        target_url=graph_state.target_repo_url or "",
        config_commit=current_commit_or_empty_tree(Path.cwd()),
        base_ref=graph_state.base_ref,
        base_commit=graph_state.base_commit or "",
        run_branch=f"run/{graph_state.run_id}",
        push_result=push_result,
        orchestrator_version=orchestrator.__version__,
        executor_kind=graph_state.executor_kind,
        effective_config_hash=_effective_config_hash(),
    )
    directory = run_dir(orch_home, project, graph_state.run_id)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / RUN_RECORD_FILENAME).write_text(
        record.model_dump_json(indent=2), encoding="utf-8"
    )


def push_if_completed(ref: RunRef, graph_state: GraphState) -> str | None:
    """C14-AC1: push only after Release approval — i.e. only once the run
    has actually reached `completed` (S8's checkpoint is Release,
    unconditional, so COMPLETED never happens without it). Returns the
    outcome string for `run.json`'s `push_result`, or `None` when there was
    nothing to push (no real target, or not completed).
    """
    if graph_state.terminal_state is not RunState.COMPLETED:
        return None
    if graph_state.target_repo_url is None:
        return None
    workspace = ref.orch_home / "workspaces" / ref.project / ref.run_id
    branch = f"run/{ref.run_id}"
    try:
        run_git(workspace, "push", "origin", branch)
    except GitCommandError as exc:
        return f"push failed: {exc}"
    return f"pushed {branch} to origin"
