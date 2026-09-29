"""engine.fsm: the shared entry points every run-touching CLI command re-enters,
rebuilding all state from disk each time (architecture-proposal.md §3.2.1) —
there is no long-running orchestrator process.

`drive()` advances a run: it loops through pending stages until it hits a stage
whose `checkpoint_after` is set (pausing at `awaiting_approval`), the run reaches
a terminal state, a stage fails (no bounded-retry loop exists yet, T7.1 — it
stops rather than re-attempting the same stage), or the graph is exhausted
(architecture-proposal.md §3.2.1 step 5: "Drive stages synchronously until the
run hits a checkpoint... or fails/stops"). `resolve_checkpoint()` and `stop_run()`
are the other half `approve`/`reject`/`answer`/`stop` call before (for approve/
reject-without-`--final`/answer) re-entering `drive()` to continue — they take
just a `RunRef` (no `scenario_id`), since by the time a checkpoint exists the
run's `scenario_id` is already persisted in graph.json.

Real run.json creation (C1-AC2's "record") is still deferred — it needs registry
lookups, config-hash computation, and real workspace/branch data not all wired
together yet.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from orchestrator.audit.approvals_log import append_approval
from orchestrator.audit.event_log import EventLog
from orchestrator.audit.run_record import atomic_write_json, read_json
from orchestrator.engine.graph import GRAPH
from orchestrator.engine.locking import acquire_lock, release_lock
from orchestrator.engine.runner import (
    StageGates,
    StageRunner,
    StageRunRequest,
    stage_commit_hook,
)
from orchestrator.engine.scheduler import BatchResult, run_batch
from orchestrator.exceptions import NoPendingApprovalError, RunAlreadyTerminalError
from orchestrator.executors.base import Executor
from orchestrator.gates.base import Gate
from orchestrator.gates.existence_gate import ExistenceGate
from orchestrator.gates.schema_gate import SchemaGate
from orchestrator.models.approvals import (
    ApprovalCheckpointKind,
    ApprovalDecision,
    ApprovalRecord,
)
from orchestrator.models.events import EventDraft, EventType
from orchestrator.models.graph import (
    GraphState,
    StageId,
    StageResult,
    StageSpec,
    StageStatus,
)
from orchestrator.models.run import RunState
from orchestrator.policies.base import Policy, PolicyOutcome, compute_diff
from orchestrator.workspace.git_ops import (
    current_commit_or_empty_tree,
    ensure_on_branch,
    init_repo,
)

GRAPH_STATE_FILENAME = "graph.json"
EVENTS_FILENAME = "events.jsonl"
APPROVALS_FILENAME = "approvals.jsonl"
DEFAULT_STAGE_TIMEOUT_SECONDS = 600
DEFAULT_STAGE_BUDGET_USD = 0.5
RUN_BRANCH_PREFIX = "run/"


@dataclass(frozen=True)
class RunRef:
    """Identifies one run, without its scenario_id (already persisted once started)."""

    orch_home: Path
    project: str
    run_id: str


@dataclass(frozen=True)
class DriveRequest:
    """Which run to advance, and (for a brand-new run) its scenario_id."""

    orch_home: Path
    project: str
    run_id: str
    scenario_id: str

    @property
    def ref(self) -> RunRef:
        """This request's run, without the scenario_id."""
        return RunRef(self.orch_home, self.project, self.run_id)


@dataclass(frozen=True)
class DriveResult:
    """What one drive() call accomplished — every stage the loop ran, in order."""

    ran_stages: tuple[StageId, ...]
    graph_state: GraphState


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


def _gates_for(stage_id: StageId) -> StageGates:
    """Every stage gets the stub SchemaGate; S2 also gets the stub ExistenceGate
    on exit ("every referenced file/symbol exists", §7's S2 exit-gate row)."""
    exit_gates: tuple[Gate, ...] = (SchemaGate(),)
    if stage_id is StageId.S2_CODEBASE_ANALYSIS:
        exit_gates = (*exit_gates, ExistenceGate())
    return StageGates(entry=(SchemaGate(),), exit=exit_gates)


def _all_stages_passed(graph_state: GraphState) -> bool:
    return all(
        graph_state.stages.get(stage_id, StageResult(stage_id=stage_id)).status
        is StageStatus.PASSED
        for stage_id in GRAPH
    )


def _complete_if_all_stages_passed(graph_state: GraphState) -> None:
    """The single place `terminal_state = COMPLETED` (D-14) gets decided.

    Called from two sites that can each be "the last thing that finishes a
    run" — drive() (a stage passes with no checkpoint attached) and
    resolve_checkpoint() (clearing the last checkpoint, e.g. Release after S8)
    — rather than duplicating the same condition in both.
    """
    if graph_state.terminal_state is None and _all_stages_passed(graph_state):
        graph_state.terminal_state = RunState.COMPLETED


def _next_ready_batch(graph_state: GraphState) -> tuple[StageSpec, ...]:
    """Every not-yet-passed stage whose dependencies are all satisfied.

    Usually one stage; two when a pair of parallel siblings (S5a+S5b, S7a+S7b)
    both become ready at once, since both depend on the same upstream stage
    (T6.1) rather than chaining — the batch size follows purely from the
    graph's shape, nothing here hardcodes which stages pair up.
    """
    ready = []
    for stage_id, spec in GRAPH.items():
        result = graph_state.stages.get(stage_id)
        if result is not None and result.status is StageStatus.PASSED:
            continue
        if all(
            graph_state.stages.get(dep, StageResult(stage_id=dep)).status
            is StageStatus.PASSED
            for dep in spec.depends_on
        ):
            ready.append(spec)
    return tuple(ready)


def _state_path(ref: RunRef) -> Path:
    return run_dir(ref.orch_home, ref.project, ref.run_id) / GRAPH_STATE_FILENAME


def _load_or_init_graph_state(request: DriveRequest) -> GraphState:
    state_path = _state_path(request.ref)
    if state_path.is_file():
        return read_json(state_path, GraphState)
    return GraphState(run_id=request.run_id, scenario_id=request.scenario_id)


def _load_existing_graph_state(ref: RunRef) -> GraphState:
    """Load state for a run that must already exist (resolve_checkpoint/stop_run)."""
    return read_json(_state_path(ref), GraphState)


@dataclass(frozen=True)
class _LoopResources:
    """What every iteration of drive()'s loop needs, computed once per call."""

    ref: RunRef
    executor: Executor
    event_log: EventLog
    workspace: Path


def _build_runner(resources: _LoopResources, spec: StageSpec) -> StageRunner:
    return StageRunner(
        executor=resources.executor,
        event_log=resources.event_log,
        clock=lambda: datetime.now(UTC),
        gates=_gates_for(spec.stage_id),
        commit_hook=stage_commit_hook,
    )


def _build_request(
    resources: _LoopResources, graph_state: GraphState, spec: StageSpec
) -> StageRunRequest:
    return StageRunRequest(
        spec=spec,
        run_id=resources.ref.run_id,
        scenario_id=graph_state.scenario_id,
        workspace_path=resources.workspace,
        rendered_prompt=f"stage {spec.stage_id.value}",
        timeout_seconds=DEFAULT_STAGE_TIMEOUT_SECONDS,
        budget_usd=DEFAULT_STAGE_BUDGET_USD,
    )


def _evaluate_s6_policies(
    resources: _LoopResources, graph_state: GraphState, policies: tuple[Policy, ...]
) -> bool:
    """Run every C6 policy against the run's accumulated diff (S6's real exit
    gate, requirements.md §7's "...all policies; change-control approval if
    triggered"), and apply the dynamic-checkpoint/critical-stop override S6
    needs — its `StageSpec.checkpoint_after` stays `None` (T6.2's shared
    dynamic-checkpoint primitive, the same mechanism T7.4 needs for
    Clarification). Worst outcome wins: a critical hit stops the run outright
    (C9's "critical violation"); otherwise a change-control hit pauses for
    approval; otherwise S6 simply stays passed and the loop continues to S7.
    Returns whether it paused/stopped the run, so the caller knows whether a
    clean pass should still fall through to the normal completion check.
    """
    base_commit = graph_state.base_commit or current_commit_or_empty_tree(
        resources.workspace
    )
    diff = compute_diff(resources.workspace, base_commit)
    results = [policy.check(diff) for policy in policies]
    for result in results:
        resources.event_log.append(
            EventDraft(
                run_id=resources.ref.run_id,
                event_type=EventType.POLICY_RESULT,
                recorded_at=datetime.now(UTC),
                stage=StageId.S6_VERIFY.value,
                payload={
                    "policy_id": result.policy_id,
                    "passed": result.passed,
                    "outcome": result.outcome.value,
                    "violations": list(result.violations),
                },
            )
        )

    if any(result.outcome is PolicyOutcome.CRITICAL for result in results):
        graph_state.terminal_state = RunState.STOPPED
        resources.event_log.append(
            EventDraft(
                run_id=resources.ref.run_id,
                event_type=EventType.STOP,
                recorded_at=datetime.now(UTC),
                payload={"reason": "critical policy violation"},
            )
        )
        return True
    if any(result.outcome is PolicyOutcome.CHANGE_CONTROL for result in results):
        graph_state.pending_checkpoint = ApprovalCheckpointKind.CHANGE_CONTROL
        resources.event_log.append(
            EventDraft(
                run_id=resources.ref.run_id,
                event_type=EventType.APPROVAL_REQUESTED,
                recorded_at=datetime.now(UTC),
                stage=StageId.S6_VERIFY.value,
                payload={"checkpoint": ApprovalCheckpointKind.CHANGE_CONTROL.value},
            )
        )
        return True
    return False


def _record_batch_result(
    resources: _LoopResources,
    graph_state: GraphState,
    batch_result: BatchResult,
    policies: tuple[Policy, ...],
) -> StageStatus:
    """Record one batch member's result (and, if applicable, its checkpoint
    pause or run-completion) into `graph_state`. Runs only on the caller's own
    thread, after every batch member has already finished — never called
    concurrently, so no lock is needed here (unlike the work `run_batch` fans
    out, which does need — and gets — serialization at the EventLog/git layers).
    """
    spec = batch_result.spec
    result = batch_result.result
    graph_state.stages[spec.stage_id] = StageResult(
        stage_id=spec.stage_id,
        status=result.status,
        attempts=1,
        commits=(result.commit,) if result.commit else (),
    )
    if result.status is not StageStatus.PASSED:
        pass
    elif spec.stage_id is StageId.S6_VERIFY:
        if not _evaluate_s6_policies(resources, graph_state, policies):
            _complete_if_all_stages_passed(graph_state)
    elif spec.checkpoint_after is not None:
        graph_state.pending_checkpoint = spec.checkpoint_after
        resources.event_log.append(
            EventDraft(
                run_id=resources.ref.run_id,
                event_type=EventType.APPROVAL_REQUESTED,
                recorded_at=datetime.now(UTC),
                stage=spec.stage_id.value,
                payload={"checkpoint": spec.checkpoint_after.value},
            )
        )
    else:
        _complete_if_all_stages_passed(graph_state)
    return result.status


def drive(
    request: DriveRequest,
    executor: Executor,
    max_run_duration_seconds: float,
    policies: tuple[Policy, ...] = (),
) -> DriveResult:
    """Reload state from disk; loop ready-stage batches until paused, terminal,
    a stage fails, or the graph is exhausted. A batch is usually one stage, but
    is two when a pair of parallel siblings (S5a+S5b, S7a+S7b) both become ready
    at once — engine/scheduler.py runs those concurrently (T6.1). State is
    persisted after every batch (not just at the end) so a process killed
    mid-loop leaves graph.json consistent with events.jsonl, not stale.

    `policies` defaults to empty (no S6 policy checks at all) rather than
    loading `config/defaults.toml` itself — that would make this function's
    behavior depend on the current working directory. Real usage (the CLI
    commands) explicitly passes `policies.registry.build_default_policies()`;
    tests that don't care about S6's policies (most of them) need no changes.
    """
    ref = request.ref
    acquire_lock(ref.orch_home, ref.project, ref.run_id, max_run_duration_seconds)
    try:
        graph_state = _load_or_init_graph_state(request)
        workspace = workspace_dir(ref.orch_home, ref.project, ref.run_id)
        # Real clone/template-copy is S0's still-deferred real prepare logic;
        # this just guarantees the minimum a commit-bearing stage needs — a
        # directory that's already a git repo (idempotent: a no-op if S0's real
        # logic already set one up here first).
        init_repo(workspace)
        # D-5: create/switch to the run branch before any stage executes, so
        # the run is never left on main — main_protection's policy check would
        # otherwise (correctly) flag every run, since nothing else does this
        # yet (S0's real prepare logic is the eventual real owner).
        ensure_on_branch(workspace, f"{RUN_BRANCH_PREFIX}{ref.run_id}")
        if graph_state.base_commit is None:
            # Captured once, at the run's very first drive() call, so every S6
            # policy check diffs the whole run's own changes, not the target
            # repo's entire history.
            graph_state.base_commit = current_commit_or_empty_tree(workspace)
        resources = _LoopResources(
            ref=ref,
            executor=executor,
            event_log=EventLog(
                run_dir(ref.orch_home, ref.project, ref.run_id) / EVENTS_FILENAME
            ),
            workspace=workspace,
        )

        ran_stages: list[StageId] = []
        while (
            graph_state.terminal_state is None
            and graph_state.pending_checkpoint is None
        ):
            batch_specs = _next_ready_batch(graph_state)
            if not batch_specs:
                break
            batch_results = run_batch(
                batch_specs,
                build_runner=lambda spec: _build_runner(resources, spec),
                build_request=lambda spec: _build_request(resources, graph_state, spec),
            )
            statuses = [
                _record_batch_result(resources, graph_state, batch_result, policies)
                for batch_result in batch_results
            ]
            ran_stages.extend(
                batch_result.spec.stage_id for batch_result in batch_results
            )
            atomic_write_json(_state_path(ref), graph_state)
            if any(status is not StageStatus.PASSED for status in statuses):
                break

        return DriveResult(ran_stages=tuple(ran_stages), graph_state=graph_state)
    finally:
        release_lock(ref.orch_home, ref.project)


def resolve_checkpoint(
    ref: RunRef,
    decision: ApprovalDecision,
    comment: str,
    approver: str,
    max_run_duration_seconds: float,
) -> GraphState:
    """Record an approve/reject/answer decision and clear the pending checkpoint.

    Raises NoPendingApprovalError if the run isn't actually paused. `reject` with
    ApprovalDecision.REJECT_FINAL ends the run as `rejected` (D-14); every other
    decision just clears the checkpoint so a later drive() call continues — real
    rejection-driven re-planning (feedback -> re-run S3+) is T7.2's job, not this
    task's; `comment` is still faithfully recorded either way (C7-AC2/AC3).
    """
    acquire_lock(ref.orch_home, ref.project, ref.run_id, max_run_duration_seconds)
    try:
        graph_state = _load_existing_graph_state(ref)
        if graph_state.pending_checkpoint is None:
            raise NoPendingApprovalError(ref.run_id)

        checkpoint = graph_state.pending_checkpoint
        now = datetime.now(UTC)
        append_approval(
            run_dir(ref.orch_home, ref.project, ref.run_id) / APPROVALS_FILENAME,
            ApprovalRecord(
                checkpoint=checkpoint,
                artifact_hashes=(),
                decision=decision,
                comment=comment,
                approver=approver,
                decided_at=now,
            ),
        )
        event_log = EventLog(
            run_dir(ref.orch_home, ref.project, ref.run_id) / EVENTS_FILENAME
        )
        event_log.append(
            EventDraft(
                run_id=ref.run_id,
                event_type=EventType.APPROVAL_RECORDED,
                recorded_at=now,
                payload={"checkpoint": checkpoint.value, "decision": decision.value},
            )
        )

        graph_state.pending_checkpoint = None
        if decision is ApprovalDecision.REJECT_FINAL:
            graph_state.terminal_state = RunState.REJECTED
        else:
            # Clearing the last checkpoint (Release, after S8) with nothing else
            # pending can complete the run (D-14) — drive()'s own completion
            # check never runs for S8 since it takes the checkpoint branch, not
            # the "stage passed with no checkpoint" branch.
            _complete_if_all_stages_passed(graph_state)
        atomic_write_json(_state_path(ref), graph_state)
        return graph_state
    finally:
        release_lock(ref.orch_home, ref.project)


def stop_run(ref: RunRef, reason: str, max_run_duration_seconds: float) -> GraphState:
    """Halt the run for safety/control regardless of the work (D-14)."""
    acquire_lock(ref.orch_home, ref.project, ref.run_id, max_run_duration_seconds)
    try:
        graph_state = _load_existing_graph_state(ref)
        if graph_state.terminal_state is not None:
            raise RunAlreadyTerminalError(ref.run_id, graph_state.terminal_state.value)

        event_log = EventLog(
            run_dir(ref.orch_home, ref.project, ref.run_id) / EVENTS_FILENAME
        )
        event_log.append(
            EventDraft(
                run_id=ref.run_id,
                event_type=EventType.STOP,
                recorded_at=datetime.now(UTC),
                payload={"reason": reason},
            )
        )
        graph_state.pending_checkpoint = None
        graph_state.terminal_state = RunState.STOPPED
        atomic_write_json(_state_path(ref), graph_state)
        return graph_state
    finally:
        release_lock(ref.orch_home, ref.project)
