"""engine.fsm.drive(): the shared entry point every run-touching CLI command
re-enters, rebuilding all state from disk each time (architecture-proposal.md
§3.2.1) — there is no long-running orchestrator process.

T2.3 scope: processes exactly one pending stage per call. GRAPH only has S0/S1
and no approval-checkpoint logic exists yet (T3.1/T3.2 replace this "one stage
per call" rule with "keep going until a checkpoint or the graph is exhausted").
Real run.json creation (C1-AC2's "record") is also deferred — it needs registry
lookups, config-hash computation, and real workspace/branch data that isn't all
wired together until T3.2; writing a placeholder-filled run.json now would just
have to be redone.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from orchestrator.audit.event_log import EventLog
from orchestrator.audit.run_record import atomic_write_json, read_json
from orchestrator.engine.graph import GRAPH
from orchestrator.engine.locking import acquire_lock, release_lock
from orchestrator.engine.runner import StageRunner, StageRunRequest
from orchestrator.executors.base import Executor
from orchestrator.models.graph import (
    GraphState,
    StageId,
    StageResult,
    StageSpec,
    StageStatus,
)

GRAPH_STATE_FILENAME = "graph.json"
EVENTS_FILENAME = "events.jsonl"
DEFAULT_STAGE_TIMEOUT_SECONDS = 600
DEFAULT_STAGE_BUDGET_USD = 0.5


def run_dir(orch_home: Path, project: str, run_id: str) -> Path:
    """ORCH_HOME/runs/<project>/<run-id>/ (requirements.md §8)."""
    return orch_home / "runs" / project / run_id


def workspace_dir(orch_home: Path, project: str, run_id: str) -> Path:
    """ORCH_HOME/workspaces/<project>/<run-id>/ (requirements.md §8)."""
    return orch_home / "workspaces" / project / run_id


def generate_run_id(
    orch_home: Path, project: str, scenario_id: str, today: date
) -> str:
    """`<scenario>-<YYYYMMDD>-<seq>` (requirements.md §11)."""
    date_str = today.strftime("%Y%m%d")
    prefix = f"{scenario_id}-{date_str}-"
    project_runs_dir = orch_home / "runs" / project
    existing_seqs = [
        int(entry.name[len(prefix) :])
        for entry in (project_runs_dir.iterdir() if project_runs_dir.is_dir() else [])
        if entry.name.startswith(prefix) and entry.name[len(prefix) :].isdigit()
    ]
    next_seq = max(existing_seqs, default=0) + 1
    return f"{prefix}{next_seq:03d}"


@dataclass(frozen=True)
class DriveRequest:
    """Which run to advance, and where its state lives."""

    orch_home: Path
    project: str
    run_id: str
    scenario_id: str


@dataclass(frozen=True)
class DriveResult:
    """What one drive() call accomplished."""

    ran_stage: StageId | None
    graph_state: GraphState


def _next_pending_stage(graph_state: GraphState) -> StageSpec | None:
    for stage_id, spec in GRAPH.items():
        result = graph_state.stages.get(stage_id)
        if result is not None and result.status is StageStatus.PASSED:
            continue
        if all(
            graph_state.stages.get(dep, StageResult(stage_id=dep)).status
            is StageStatus.PASSED
            for dep in spec.depends_on
        ):
            return spec
    return None


def _load_or_init_graph_state(state_path: Path, run_id: str) -> GraphState:
    if state_path.is_file():
        return read_json(state_path, GraphState)
    return GraphState(run_id=run_id)


def drive(
    request: DriveRequest, executor: Executor, max_run_duration_seconds: float
) -> DriveResult:
    """Reload state from disk, run the next pending stage (if any), persist, return."""
    acquire_lock(
        request.orch_home, request.project, request.run_id, max_run_duration_seconds
    )
    try:
        state_path = (
            run_dir(request.orch_home, request.project, request.run_id)
            / GRAPH_STATE_FILENAME
        )
        graph_state = _load_or_init_graph_state(state_path, request.run_id)

        spec = _next_pending_stage(graph_state)
        if spec is None:
            return DriveResult(ran_stage=None, graph_state=graph_state)

        workspace = workspace_dir(request.orch_home, request.project, request.run_id)
        workspace.mkdir(parents=True, exist_ok=True)
        event_log = EventLog(
            run_dir(request.orch_home, request.project, request.run_id)
            / EVENTS_FILENAME
        )
        runner = StageRunner(
            executor=executor, event_log=event_log, clock=lambda: datetime.now(UTC)
        )

        result = runner.run(
            StageRunRequest(
                spec=spec,
                run_id=request.run_id,
                scenario_id=request.scenario_id,
                workspace_path=workspace,
                rendered_prompt=f"stage {spec.stage_id.value}",
                timeout_seconds=DEFAULT_STAGE_TIMEOUT_SECONDS,
                budget_usd=DEFAULT_STAGE_BUDGET_USD,
            )
        )

        graph_state.stages[spec.stage_id] = StageResult(
            stage_id=spec.stage_id,
            status=result.status,
            attempts=1,
            commits=(result.commit,) if result.commit else (),
        )
        atomic_write_json(state_path, graph_state)
        return DriveResult(ran_stage=spec.stage_id, graph_state=graph_state)
    finally:
        release_lock(request.orch_home, request.project)
