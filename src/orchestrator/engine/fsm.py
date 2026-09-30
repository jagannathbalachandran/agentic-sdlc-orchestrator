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

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path

from orchestrator.audit.approvals_log import append_approval
from orchestrator.audit.decisions_log import append_decision, next_decision_id
from orchestrator.audit.event_log import EventLog
from orchestrator.audit.run_record import atomic_write_json, read_json
from orchestrator.config.schema import RetryLimits
from orchestrator.engine.graph import GRAPH
from orchestrator.engine.locking import acquire_lock, release_lock
from orchestrator.engine.replanning import invalidate_from
from orchestrator.engine.runner import (
    CommitTrailerContext,
    StageGates,
    StageRunner,
    StageRunRequest,
    StageRunResult,
    commit_message_with_trailers,
    no_op_commit,
    stage_commit_hook,
)
from orchestrator.engine.scheduler import BatchResult, run_batch
from orchestrator.exceptions import (
    NoCheckpointRecordedError,
    NoPendingApprovalError,
    RunAlreadyTerminalError,
)
from orchestrator.executors.base import Executor
from orchestrator.gates.base import Gate
from orchestrator.gates.existence_gate import ExistenceGate
from orchestrator.gates.schema_gate import SchemaGate
from orchestrator.gates.traceability_gate import (
    DesignCitationGate,
    PlanCitationGate,
    RequirementsCitationGate,
)
from orchestrator.models.approvals import (
    ApprovalCheckpointKind,
    ApprovalDecision,
    ApprovalRecord,
)
from orchestrator.models.decisions import Decision
from orchestrator.models.events import EventDraft, EventType
from orchestrator.models.graph import (
    CommitStrategy,
    GraphState,
    StageId,
    StageResult,
    StageSpec,
    StageStatus,
)
from orchestrator.models.run import RunState
from orchestrator.policies.base import Policy, PolicyOutcome, compute_diff
from orchestrator.workspace.git_ops import (
    commit_all,
    current_commit_or_empty_tree,
    ensure_on_branch,
    init_repo,
    rollback_to,
)

GRAPH_STATE_FILENAME = "graph.json"
EVENTS_FILENAME = "events.jsonl"
APPROVALS_FILENAME = "approvals.jsonl"
DECISIONS_FILENAME = "decisions.jsonl"
DEFAULT_STAGE_TIMEOUT_SECONDS = 600
DEFAULT_STAGE_BUDGET_USD = 0.5
RUN_BRANCH_PREFIX = "run/"
DEFAULT_RETRY_LIMITS = RetryLimits(
    invalid_output_max_attempts=2,
    s6_failure_max_attempts=3,
    s7b_findings_max_attempts=2,
)
DEFAULT_MAX_AGENT_CALLS = 60


@dataclass(frozen=True)
class ReliabilityLimits:
    """The bounded-retry and safe-stop numbers `drive()` enforces (T7.1)."""

    retry_limits: RetryLimits = field(default_factory=lambda: DEFAULT_RETRY_LIMITS)
    max_agent_calls: int = DEFAULT_MAX_AGENT_CALLS


DEFAULT_RELIABILITY_LIMITS = ReliabilityLimits()


@dataclass(frozen=True)
class RunRef:
    """Identifies one run, without its scenario_id (already persisted once started)."""

    orch_home: Path
    project: str
    run_id: str


@dataclass(frozen=True)
class DriveRequest:
    """Which run to advance, and (for a brand-new run) its scenario_id.

    `inject_fault` (G-16) only matters the first time a run's GraphState is
    created — it's copied onto `GraphState.inject_fault` there and persists
    from then on, so `approve`/`reject`/`answer` re-entering `drive()` for an
    existing run don't need to (and can't easily) re-supply it.
    """

    orch_home: Path
    project: str
    run_id: str
    scenario_id: str
    inject_fault: bool = False

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


def _traceability_gate_for(stage_id: StageId) -> Gate | None:
    if stage_id is StageId.S1_REQUIREMENTS:
        return RequirementsCitationGate()
    if stage_id is StageId.S3_DESIGN:
        return DesignCitationGate()
    if stage_id is StageId.S4_PLAN:
        return PlanCitationGate()
    return None


def _gates_for(stage_id: StageId) -> StageGates:
    """Every stage gets the stub SchemaGate; S2 also gets the stub
    ExistenceGate on exit ("every referenced file/symbol exists", §7's S2
    exit-gate row); S1/S3/S4 get their real citation gate (T8.1, C10-AC1).
    """
    exit_gates: tuple[Gate, ...] = (SchemaGate(),)
    if stage_id is StageId.S2_CODEBASE_ANALYSIS:
        exit_gates = (*exit_gates, ExistenceGate())
    traceability_gate = _traceability_gate_for(stage_id)
    if traceability_gate is not None:
        exit_gates = (*exit_gates, traceability_gate)
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
    return GraphState(
        run_id=request.run_id,
        scenario_id=request.scenario_id,
        inject_fault=request.inject_fault,
    )


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
    max_run_duration_seconds: float


def _build_runner(resources: _LoopResources, spec: StageSpec) -> StageRunner:
    return StageRunner(
        executor=resources.executor,
        event_log=resources.event_log,
        clock=lambda: datetime.now(UTC),
        gates=_gates_for(spec.stage_id),
        commit_hook=stage_commit_hook,
    )


def _rendered_prompt_for(spec: StageSpec, graph_state: GraphState) -> str:
    prompt = f"stage {spec.stage_id.value}"
    if spec.stage_id is StageId.S1_REQUIREMENTS and graph_state.clarification_answer:
        # T7.4: S1 re-running after a Clarification answer gets that answer as
        # additional context — the minimum viable form of "available to the
        # analyst profile", matching how every other stage's prompt is still
        # just this placeholder (real profile-rendered prompts aren't wired
        # into engine/fsm.py at all yet, Phase 1 scope).
        prompt += f"\n\nHuman answer to blocking questions: {graph_state.clarification_answer}"
    return prompt


def _build_request(
    resources: _LoopResources, graph_state: GraphState, spec: StageSpec
) -> StageRunRequest:
    # +1: this call is about to become that stage's *next* attempt — its
    # StageResult (if any) still holds the *last completed* attempt's count.
    next_attempt = (
        graph_state.stages.get(
            spec.stage_id, StageResult(stage_id=spec.stage_id)
        ).attempts
        + 1
    )
    return StageRunRequest(
        spec=spec,
        run_id=resources.ref.run_id,
        scenario_id=graph_state.scenario_id,
        workspace_path=resources.workspace,
        rendered_prompt=_rendered_prompt_for(spec, graph_state),
        timeout_seconds=DEFAULT_STAGE_TIMEOUT_SECONDS,
        budget_usd=DEFAULT_STAGE_BUDGET_USD,
        attempt=next_attempt,
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


def _max_attempts_for(stage_id: StageId, retry_limits: RetryLimits) -> int:
    """Which bounded-retry count applies to this stage (C9, three separate
    loops: S6-failure, S7b-findings, and invalid-output for everything else —
    the current codebase has no real signal distinguishing "invalid output"
    from any other stage failure, so `invalid_output_max_attempts` is used
    generically for every stage except S6/S7b, which have their own explicit
    counts and their own real trigger signals).
    """
    if stage_id is StageId.S6_VERIFY:
        return retry_limits.s6_failure_max_attempts
    if stage_id is StageId.S7B_REVIEW:
        return retry_limits.s7b_findings_max_attempts
    return retry_limits.invalid_output_max_attempts


def _fallback_to_human(
    resources: _LoopResources,
    graph_state: GraphState,
    stage_id: StageId,
    attempts: int,
    reason: str,
) -> None:
    """C9: exhausted retries -> pause for the human with full context, ending
    as failed rather than silently stopping — the human decides whether to
    intervene, re-plan, or leave it as `failed`.
    """
    graph_state.terminal_state = RunState.FAILED
    resources.event_log.append(
        EventDraft(
            run_id=resources.ref.run_id,
            event_type=EventType.STOP,
            recorded_at=datetime.now(UTC),
            stage=stage_id.value,
            payload={"reason": reason, "attempts": attempts},
        )
    )


def _run_fix_call(
    resources: _LoopResources, graph_state: GraphState, subject: str, attempt: int
) -> None:
    """One targeted developer fix call (G-13), scoped to whatever just failed
    — not a full re-run of S5a's own task loop. Committed with its own
    `Stage: S5a-fix` trailer (C10-AC2), never `S5a`, so it's never misread as
    original implementation work; `Task`/`FR`/`Req` trailers are omitted (real
    per-task attribution isn't built — see commit_message_with_trailers).
    `attempt` (the retry count that triggered this fix call, offset by 1)
    keys its own mock fixture distinctly from S5a's original implementation
    call, which is always attempt 1.
    """
    fix_spec = StageSpec(
        stage_id=StageId.S5A_IMPLEMENT,
        owner_profile="developer",
        commit_strategy=CommitStrategy.NONE,
    )
    runner = StageRunner(
        executor=resources.executor,
        event_log=resources.event_log,
        clock=lambda: datetime.now(UTC),
        gates=StageGates(),
        commit_hook=no_op_commit,
    )
    result = runner.run(
        StageRunRequest(
            spec=fix_spec,
            run_id=resources.ref.run_id,
            scenario_id=graph_state.scenario_id,
            workspace_path=resources.workspace,
            rendered_prompt=subject,
            timeout_seconds=DEFAULT_STAGE_TIMEOUT_SECONDS,
            budget_usd=DEFAULT_STAGE_BUDGET_USD,
            attempt=attempt + 1,
        )
    )
    graph_state.agent_call_count += 1
    if result.status is StageStatus.PASSED:
        message = commit_message_with_trailers(
            subject,
            CommitTrailerContext(run_id=resources.ref.run_id, stage_label="S5a-fix"),
        )
        commit_all(resources.workspace, message)


def _invalidate(graph_state: GraphState, stage_id: StageId, attempts: int = 0) -> None:
    graph_state.stages[stage_id] = StageResult(
        stage_id=stage_id, status=StageStatus.INVALIDATED, attempts=attempts
    )


def _handle_stage_failure(
    resources: _LoopResources,
    graph_state: GraphState,
    spec: StageSpec,
    attempts: int,
    retry_limits: RetryLimits,
) -> None:
    """A stage's own agent call failed (invalid output / error / timeout, or a
    gate rejected its output). S6 gets a fix call before its next attempt
    (G-13); every other stage (including S7b failing outright, as opposed to
    passing with findings — handled separately) just retries the same call —
    it stays FAILED here and `_next_ready_batch` naturally re-selects it next
    iteration, since a FAILED stage is never treated as already-passed.
    """
    max_attempts = _max_attempts_for(spec.stage_id, retry_limits)
    if attempts >= max_attempts:
        _fallback_to_human(
            resources,
            graph_state,
            spec.stage_id,
            attempts,
            f"{spec.stage_id.value} failed after {attempts} attempt(s)",
        )
        return
    if spec.stage_id is StageId.S6_VERIFY:
        _run_fix_call(
            resources, graph_state, "S5a-fix: address S6 verification failure", attempts
        )


def _handle_s7b_findings(
    resources: _LoopResources,
    graph_state: GraphState,
    attempts: int,
    retry_limits: RetryLimits,
) -> None:
    """S7b passed its own call but reported high-severity findings (G-15): a
    fix call, then S6/S7a/S7b are all invalidated and re-run — not just S7b —
    since a findings-driven fix can change the API surface S7a already
    documented (matching C11-AC2's invalidation principle).
    """
    max_attempts = retry_limits.s7b_findings_max_attempts
    if attempts >= max_attempts:
        _fallback_to_human(
            resources,
            graph_state,
            StageId.S7B_REVIEW,
            attempts,
            f"S7b reported high-severity findings after {attempts} attempt(s)",
        )
        return
    _run_fix_call(
        resources, graph_state, "S5a-fix: address S7b review findings", attempts
    )
    _invalidate(graph_state, StageId.S6_VERIFY)
    _invalidate(graph_state, StageId.S7A_DOCS)
    _invalidate(graph_state, StageId.S7B_REVIEW, attempts=attempts)


INJECTED_FAULT_TEST_PATH = "tests/acceptance/test_injected_fault.py"
INJECTED_FAULT_TEST_CONTENT = (
    '"""Deliberately failing test, written by the orchestrator itself (G-16) to\n'
    "demonstrate the S6->S5a retry loop on demand, not organically discovered.\n"
    '"""\n\n'
    "from __future__ import annotations\n\n\n"
    "def test_injected_fault() -> None:\n"
    '    raise AssertionError("G-16: deliberately injected fault")\n'
)


def _inject_fault(
    resources: _LoopResources, graph_state: GraphState, attempt: int
) -> None:
    """G-16: write one failing acceptance test, attributed to the orchestrator
    itself (not an agent) — deterministically forces exactly one S6 failure so
    the S6->S5a retry loop (G-13) is reliably demonstrable, rather than
    depending on a real agent call happening to fail on its own. `injected`
    (a first-class `EventDraft` field, not buried in payload) keeps this event
    trivially distinguishable from an organic failure in `events.jsonl`.
    """
    test_path = resources.workspace / INJECTED_FAULT_TEST_PATH
    test_path.parent.mkdir(parents=True, exist_ok=True)
    test_path.write_text(INJECTED_FAULT_TEST_CONTENT, encoding="utf-8")
    resources.event_log.append(
        EventDraft(
            run_id=resources.ref.run_id,
            event_type=EventType.FAULT_INJECTED,
            recorded_at=datetime.now(UTC),
            stage=StageId.S6_VERIFY.value,
            attempt=attempt,
            payload={"file": INJECTED_FAULT_TEST_PATH},
            injected=True,
        )
    )
    graph_state.fault_injected = True


def _record_batch_result(
    resources: _LoopResources,
    graph_state: GraphState,
    batch_result: BatchResult,
    policies: tuple[Policy, ...],
    retry_limits: RetryLimits,
) -> None:
    """Record one batch member's result (and, if applicable, its checkpoint
    pause, retry, or run-completion) into `graph_state`. Runs only on the
    caller's own thread, after every batch member has already finished —
    never called concurrently, so no lock is needed here (unlike the work
    `run_batch` fans out, which does need — and gets — serialization at the
    EventLog/git layers). Never returns a status for the caller to check —
    every outcome (pass, checkpoint, retry, exhaustion) is fully handled here,
    via `graph_state.terminal_state`/`pending_checkpoint`.
    """
    spec = batch_result.spec
    result = batch_result.result
    attempts = (
        graph_state.stages.get(
            spec.stage_id, StageResult(stage_id=spec.stage_id)
        ).attempts
        + 1
    )

    should_inject = (
        spec.stage_id is StageId.S6_VERIFY
        and graph_state.inject_fault
        and not graph_state.fault_injected
        and attempts == 1
    )
    if should_inject:
        _inject_fault(resources, graph_state, attempts)
        # No real "run the target's test suite" mechanism exists yet (Phase 1
        # scope) for the injected test to actually fail against — this is the
        # deterministic stand-in until that real integration lands.
        result = StageRunResult(
            status=StageStatus.FAILED, response=result.response, commit=None
        )

    graph_state.stages[spec.stage_id] = StageResult(
        stage_id=spec.stage_id,
        status=result.status,
        attempts=attempts,
        commits=(result.commit,) if result.commit else (),
    )
    graph_state.agent_call_count += 1
    if result.status is StageStatus.PASSED:
        graph_state.last_checkpoint_commit = current_commit_or_empty_tree(
            resources.workspace
        )

    is_s7b_findings = (
        spec.stage_id is StageId.S7B_REVIEW
        and result.status is StageStatus.PASSED
        and result.response.high_severity_findings
    )
    is_s1_clarification = (
        spec.stage_id is StageId.S1_REQUIREMENTS
        and result.status is StageStatus.PASSED
        and bool(result.response.blocking_questions)
    )
    if is_s7b_findings:
        _handle_s7b_findings(resources, graph_state, attempts, retry_limits)
    elif is_s1_clarification:
        # C7/T7.4: S1's own StageSpec.checkpoint_after stays None (same
        # reasoning as S6's Change-control, T6.2) — this dynamic override sets
        # pending_checkpoint only when S1 actually raised blocking questions.
        graph_state.pending_checkpoint = ApprovalCheckpointKind.CLARIFICATION
        resources.event_log.append(
            EventDraft(
                run_id=resources.ref.run_id,
                event_type=EventType.APPROVAL_REQUESTED,
                recorded_at=datetime.now(UTC),
                stage=spec.stage_id.value,
                payload={
                    "checkpoint": ApprovalCheckpointKind.CLARIFICATION.value,
                    "blocking_questions": list(result.response.blocking_questions),
                },
            )
        )
    elif result.status is not StageStatus.PASSED:
        _handle_stage_failure(resources, graph_state, spec, attempts, retry_limits)
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


def _check_safe_stop_limits(
    resources: _LoopResources, graph_state: GraphState, reliability: ReliabilityLimits
) -> bool:
    """C9 safe-stop: max agent calls, or max run duration, exceeded -> stop
    (not a retry-exhaustion fallback — a safety cap, always terminal STOPPED,
    with no partial commit left behind since it's checked between batches,
    never mid-stage). Returns whether it stopped the run. A no-op if the run
    already reached a terminal state this same batch (e.g. COMPLETED) —
    safe-stop must never overwrite a legitimate outcome that just happened.
    """
    if graph_state.terminal_state is not None:
        return False
    if graph_state.agent_call_count > reliability.max_agent_calls:
        reason = f"max_agent_calls ({reliability.max_agent_calls}) exceeded"
    elif (
        graph_state.started_at is not None
        and (datetime.now(UTC) - graph_state.started_at).total_seconds()
        > resources.max_run_duration_seconds
    ):
        reason = "max run duration exceeded"
    else:
        return False
    graph_state.terminal_state = RunState.STOPPED
    resources.event_log.append(
        EventDraft(
            run_id=resources.ref.run_id,
            event_type=EventType.STOP,
            recorded_at=datetime.now(UTC),
            payload={"reason": reason},
        )
    )
    return True


def drive(
    request: DriveRequest,
    executor: Executor,
    max_run_duration_seconds: float,
    policies: tuple[Policy, ...] = (),
    reliability: ReliabilityLimits = DEFAULT_RELIABILITY_LIMITS,
) -> DriveResult:
    """Reload state from disk; loop ready-stage batches until paused, terminal,
    or the graph is exhausted. A batch is usually one stage, but is two when a
    pair of parallel siblings (S5a+S5b, S7a+S7b) both become ready at once —
    engine/scheduler.py runs those concurrently (T6.1). State is persisted
    after every batch (not just at the end) so a process killed mid-loop
    leaves graph.json consistent with events.jsonl, not stale.

    A stage failing no longer breaks the loop outright (T7.1): bounded retries
    (invalid-output/S6-failure/S7b-findings, C9) are handled entirely inside
    `_record_batch_result` — a still-retryable failure leaves the stage FAILED
    so `_next_ready_batch` re-selects it next iteration; exhaustion sets
    `terminal_state = FAILED` itself, which is what actually stops this loop.

    `policies` defaults to empty (no S6 policy checks at all) and `reliability`
    defaults to safe built-in numbers (not `config/defaults.toml`'s own, so
    this function stays independent of the current working directory). Real
    usage (the CLI commands) passes `policies.registry.build_default_policies()`
    and could override `reliability` the same way if it ever needs to.
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
        if graph_state.started_at is None:
            graph_state.started_at = datetime.now(UTC)
        resources = _LoopResources(
            ref=ref,
            executor=executor,
            event_log=EventLog(
                run_dir(ref.orch_home, ref.project, ref.run_id) / EVENTS_FILENAME
            ),
            workspace=workspace,
            max_run_duration_seconds=max_run_duration_seconds,
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
            for batch_result in batch_results:
                _record_batch_result(
                    resources,
                    graph_state,
                    batch_result,
                    policies,
                    reliability.retry_limits,
                )
            ran_stages.extend(
                batch_result.spec.stage_id for batch_result in batch_results
            )
            _check_safe_stop_limits(resources, graph_state, reliability)
            atomic_write_json(_state_path(ref), graph_state)

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
    ApprovalDecision.REJECT_FINAL ends the run as `rejected` (D-14); rejecting a
    Design checkpoint (without `--final`) triggers real re-planning (C11: S3
    onward invalidated, S1/S2 kept — engine/replanning.py); answering a
    Clarification checkpoint (T7.4) records the answer in decisions.jsonl
    (C10-AC6, not just approvals.jsonl) and re-runs S1 onward with it as
    context; every other decision just clears the checkpoint so a later
    drive() call continues. `comment` is faithfully recorded in every case
    (C7-AC2/AC3).
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
        elif (
            decision is ApprovalDecision.REJECT
            and checkpoint is ApprovalCheckpointKind.DESIGN
        ):
            # C11: reject Design with feedback -> re-run S3 (with the
            # feedback) then S4 onward; S1/S2 are upstream of S3, so they're
            # left untouched. Downstream stages are marked invalidated, not
            # re-run directly here — the existing batch-selection machinery
            # (engine/fsm.py's drive() loop) re-selects anything not PASSED.
            invalidated = invalidate_from(graph_state, StageId.S3_DESIGN)
            event_log.append(
                EventDraft(
                    run_id=ref.run_id,
                    event_type=EventType.RETRY,
                    recorded_at=now,
                    payload={
                        "trigger": "design_rejection",
                        "invalidated": [stage.value for stage in invalidated],
                    },
                )
            )
        elif (
            decision is ApprovalDecision.ANSWER
            and checkpoint is ApprovalCheckpointKind.CLARIFICATION
        ):
            # C7/T7.4: answering blocking questions re-runs S1 (and everything
            # downstream, since nothing past S1 can be trusted until they're
            # resolved) with the answer as additional context — the same
            # invalidate-and-let-drive()-re-select mechanism as Design
            # rejection (T7.2), reused via engine/replanning.py.
            graph_state.clarification_answer = comment
            invalidated = invalidate_from(graph_state, StageId.S1_REQUIREMENTS)
            decisions_path = (
                run_dir(ref.orch_home, ref.project, ref.run_id) / DECISIONS_FILENAME
            )
            append_decision(
                decisions_path,
                Decision(
                    decision_id=next_decision_id(decisions_path, ref.run_id),
                    stage=StageId.S1_REQUIREMENTS.value,
                    actor=approver,
                    choice=comment,
                    rationale=(
                        "Human answer to blocking questions raised by S1 at the"
                        " Clarification checkpoint"
                    ),
                    recorded_at=now,
                ),
            )
            event_log.append(
                EventDraft(
                    run_id=ref.run_id,
                    event_type=EventType.RETRY,
                    recorded_at=now,
                    payload={
                        "trigger": "clarification_answer",
                        "invalidated": [stage.value for stage in invalidated],
                    },
                )
            )
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


def rollback_to_checkpoint(ref: RunRef, max_run_duration_seconds: float) -> GraphState:
    """Reset the workspace to `graph_state.last_checkpoint_commit` (T7.1,
    G-14) — the most recently recorded checkpoint, not necessarily the most
    recent commit, since several stages commit 0 times (S2, S6, S7b). A
    manual recovery action, not auto-invoked by the retry loop: it discards
    uncommitted work, so it's for a human who has decided the workspace is
    beyond fixing forward, not a step drive() takes on its own.

    Raises NoCheckpointRecordedError if no stage's exit gate has passed yet.
    """
    acquire_lock(ref.orch_home, ref.project, ref.run_id, max_run_duration_seconds)
    try:
        graph_state = _load_existing_graph_state(ref)
        if graph_state.last_checkpoint_commit is None:
            raise NoCheckpointRecordedError(ref.run_id)

        workspace = workspace_dir(ref.orch_home, ref.project, ref.run_id)
        rollback_to(workspace, graph_state.last_checkpoint_commit)

        event_log = EventLog(
            run_dir(ref.orch_home, ref.project, ref.run_id) / EVENTS_FILENAME
        )
        event_log.append(
            EventDraft(
                run_id=ref.run_id,
                event_type=EventType.ROLLBACK,
                recorded_at=datetime.now(UTC),
                payload={"checkpoint_commit": graph_state.last_checkpoint_commit},
            )
        )
        return graph_state
    finally:
        release_lock(ref.orch_home, ref.project)
