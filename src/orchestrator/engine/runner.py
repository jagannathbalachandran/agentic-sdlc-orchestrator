"""StageRunner: entry gate(s) → execute → exit gate(s) → event → commit.

Walking-skeleton scope (T2.1): drives one stage at a time on any Executor, proven
on S0/S1 with the mock executor. Policy enforcement is deliberately not stubbed
here — Policy.check needs a WorkspaceDiff type that doesn't exist until T6.1/T6.2,
so adding a placeholder now would mean redesigning it there anyway.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from orchestrator.audit.event_log import EventLog
from orchestrator.executors.base import Executor
from orchestrator.gates.base import Gate, StageContext
from orchestrator.models.agent_io import (
    AgentCallOutcome,
    AgentCallRequest,
    AgentCallResponse,
)
from orchestrator.models.events import EventDraft, EventType
from orchestrator.models.graph import (
    CommitStrategy,
    GateOutcome,
    StageSpec,
    StageStatus,
)
from orchestrator.workspace.git_ops import commit_all

Clock = Callable[[], datetime]
CommitHook = Callable[[StageContext, StageSpec], "str | None"]


def no_op_commit(_context: StageContext, _spec: StageSpec) -> str | None:
    """A commit hook that never commits — used by tests that don't touch git."""
    return None


@dataclass(frozen=True)
class CommitTrailerContext:
    """The known pieces of a commit trailer block (C10-AC2, G-13). `run_id`/
    `stage_label` are always known; `task_id`/`fr_id`/`req_id` are `None` when
    not — real per-task attribution for S5a (which would populate them for a
    normal S5a commit) isn't built yet (still one call per whole stage, not
    per task) — an explicit, documented limitation, not a silently missing
    trailer.
    """

    run_id: str
    stage_label: str
    task_id: str | None = None
    fr_id: str | None = None
    req_id: str | None = None


def commit_message_with_trailers(
    subject: str, trailer_context: CommitTrailerContext
) -> str:
    """Build a commit message with a structured trailer block: Task, FR, Req,
    Run, Stage (whichever of Task/FR/Req are known)."""
    trailers = []
    if trailer_context.task_id:
        trailers.append(f"Task: {trailer_context.task_id}")
    if trailer_context.fr_id:
        trailers.append(f"FR: {trailer_context.fr_id}")
    if trailer_context.req_id:
        trailers.append(f"Req: {trailer_context.req_id}")
    trailers.append(f"Run: {trailer_context.run_id}")
    trailers.append(f"Stage: {trailer_context.stage_label}")
    return subject + "\n\n" + "\n".join(trailers)


def stage_commit_hook(context: StageContext, spec: StageSpec) -> str | None:
    """Real commit hook (T6.1): one commit per stage call, unless the stage's
    `commit_strategy` is NONE. `commit_all` serializes concurrent callers
    internally (workspace/git_ops.py's lock), so S5a/S5b or S7a/S7b committing
    from separate threads never race the shared working tree's index.
    """
    if spec.commit_strategy is CommitStrategy.NONE:
        return None
    message = commit_message_with_trailers(
        f"{spec.stage_id.value}: stage complete",
        CommitTrailerContext(run_id=context.run_id, stage_label=spec.stage_id.value),
    )
    return commit_all(context.workspace_path, message)


@dataclass(frozen=True)
class StageGates:
    """The entry/exit gates a StageRunner enforces for one stage."""

    entry: Sequence[Gate] = ()
    exit: Sequence[Gate] = ()


@dataclass(frozen=True)
class StageRunRequest:
    """Everything one StageRunner.run() call needs."""

    spec: StageSpec
    run_id: str
    scenario_id: str
    workspace_path: Path
    rendered_prompt: str
    timeout_seconds: int
    budget_usd: float
    attempt: int = 1


@dataclass(frozen=True)
class StageRunResult:
    """What one stage run produced."""

    status: StageStatus
    response: AgentCallResponse
    commit: str | None


class StageGateFailure(Exception):
    """An entry or exit gate failed; the caller (engine/fsm.py, T2.3+) decides what
    happens next — retry, rollback, or pause for human."""

    def __init__(self, outcome: GateOutcome) -> None:
        super().__init__(f"gate failed: {outcome.gate_name}: {outcome.details}")
        self.outcome = outcome


class StageRunner:
    """Drives one stage through its full boundary lifecycle."""

    def __init__(
        self,
        executor: Executor,
        event_log: EventLog,
        clock: Clock,
        gates: StageGates | None = None,
        commit_hook: CommitHook = no_op_commit,
    ) -> None:
        self._executor = executor
        self._event_log = event_log
        self._clock = clock
        self._gates = gates if gates is not None else StageGates()
        self._commit_hook = commit_hook

    def run(self, request: StageRunRequest) -> StageRunResult:
        """Run entry gates, the agent call, exit gates, then the commit hook."""
        context = StageContext(
            run_id=request.run_id,
            stage_id=request.spec.stage_id,
            attempt=request.attempt,
            workspace_path=request.workspace_path,
        )
        self._record(context, EventType.STAGE_STARTED)
        self._run_gates(self._gates.entry, context)

        response = self._executor.execute(
            AgentCallRequest(
                profile_name=request.spec.owner_profile or "",
                scenario_id=request.scenario_id,
                stage=request.spec.stage_id.value,
                attempt=request.attempt,
                rendered_prompt=request.rendered_prompt,
                workspace_path=str(request.workspace_path),
                timeout_seconds=request.timeout_seconds,
                budget_usd=request.budget_usd,
            )
        )

        self._run_gates(self._gates.exit, context)

        status = (
            StageStatus.PASSED
            if response.outcome is AgentCallOutcome.SUCCESS
            else StageStatus.FAILED
        )
        commit = (
            self._commit_hook(context, request.spec)
            if status is StageStatus.PASSED
            else None
        )
        self._record(
            context, EventType.STAGE_FINISHED, payload={"status": status.value}
        )
        return StageRunResult(status=status, response=response, commit=commit)

    def _run_gates(self, gates: Sequence[Gate], context: StageContext) -> None:
        for gate in gates:
            outcome = gate.check(context)
            self._record(
                context,
                EventType.GATE_RESULT,
                payload={
                    "gate_name": outcome.gate_name,
                    "passed": outcome.passed,
                    "details": outcome.details,
                },
            )
            if not outcome.passed:
                raise StageGateFailure(outcome)

    def _record(
        self,
        context: StageContext,
        event_type: EventType,
        payload: dict[str, object] | None = None,
    ) -> None:
        self._event_log.append(
            EventDraft(
                run_id=context.run_id,
                event_type=event_type,
                recorded_at=self._clock(),
                stage=context.stage_id.value,
                attempt=context.attempt,
                payload=payload or {},
            )
        )
