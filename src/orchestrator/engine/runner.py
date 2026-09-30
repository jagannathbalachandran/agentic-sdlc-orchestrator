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

from orchestrator.audit.agent_transcripts import write_transcript
from orchestrator.audit.event_log import EventLog
from orchestrator.audit.stage_artifacts import write_stage_artifacts
from orchestrator.exceptions import ConfigValidationError
from orchestrator.executors.base import Executor
from orchestrator.gates.base import Gate, StageContext
from orchestrator.models.agent_io import (
    AgentCallOutcome,
    AgentCallRequest,
    AgentCallResponse,
    AgentCallTranscript,
)
from orchestrator.models.events import EventDraft, EventType
from orchestrator.models.graph import (
    CommitStrategy,
    GateOutcome,
    StageSpec,
    StageStatus,
)
from orchestrator.profiles.loader import load_profile
from orchestrator.workspace.git_ops import commit_all

Clock = Callable[[], datetime]
CommitHook = Callable[[StageContext, StageSpec], "str | None"]

NO_AGENT_RESPONSE = AgentCallResponse(
    outcome=AgentCallOutcome.SUCCESS,
    summary="orchestrator-only stage; no agent call",
    duration_seconds=0.0,
)


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
    """What one stage run produced.

    `commits` is only non-empty for a `ONE_PER_TASK` stage (S5a, T9.6) —
    every other stage still reports its single commit via `commit` alone,
    unchanged; `_record_batch_result` (engine/fsm.py) prefers `commits` when
    it's non-empty.
    """

    status: StageStatus
    response: AgentCallResponse
    commit: str | None
    commits: tuple[str, ...] = ()


class StageGateFailure(Exception):
    """An entry or exit gate failed; the caller (engine/fsm.py, T2.3+) decides what
    happens next — retry, rollback, or pause for human."""

    def __init__(self, outcome: GateOutcome) -> None:
        super().__init__(f"gate failed: {outcome.gate_name}: {outcome.details}")
        self.outcome = outcome


@dataclass(frozen=True)
class StageRunnerOptions:
    """StageRunner's secondary construction params, bundled to stay under
    the project's max-args limit. `profiles_root`/`transcripts_dir` are both
    optional (default `None`, meaning "skip this" — most direct unit-test
    construction doesn't care) — production usage (`engine/fsm.py:
    _build_runner`) always supplies real paths, so every real agent call
    gets a transcript (item 3, C8-AC4).
    """

    gates: StageGates | None = None
    commit_hook: CommitHook = no_op_commit
    profiles_root: Path | None = None
    transcripts_dir: Path | None = None
    artifacts_dir: Path | None = None


class StageRunner:
    """Drives one stage through its full boundary lifecycle."""

    def __init__(
        self,
        executor: Executor,
        event_log: EventLog,
        clock: Clock,
        options: StageRunnerOptions | None = None,
    ) -> None:
        resolved = options if options is not None else StageRunnerOptions()
        self._executor = executor
        self._event_log = event_log
        self._clock = clock
        self._gates = resolved.gates if resolved.gates is not None else StageGates()
        self._commit_hook = resolved.commit_hook
        self._profiles_root = resolved.profiles_root
        self._transcripts_dir = resolved.transcripts_dir
        self._artifacts_dir = resolved.artifacts_dir

    def run(self, request: StageRunRequest) -> StageRunResult:
        """Run entry gates, the agent call, exit gates, then the commit hook.

        A gate failure still raises `StageGateFailure` (the caller —
        `engine/scheduler.py`'s `_run_one` — is what converts it into a
        FAILED `StageRunResult`, unchanged contract) but now also records
        `stage_finished` first (item 3, C8-AC4-adjacent): previously a gate
        failure skipped that event entirely, since the exception unwound
        straight out of `run()` before reaching the event at the bottom —
        a failed stage triggered by a gate was invisible in `stage_finished`
        terms, diagnosable only by cross-referencing `gate_result` events.
        """
        context = StageContext(
            run_id=request.run_id,
            stage_id=request.spec.stage_id,
            attempt=request.attempt,
            workspace_path=request.workspace_path,
        )
        # None for an orchestrator-only stage (S0/S6/S8, requires_agent=
        # False) — there's no real agent call, so no transcript either;
        # an id implying one exists would be misleading.
        agent_call_id = (
            f"{context.stage_id.value}-{context.attempt}"
            if request.spec.requires_agent
            else None
        )
        self._record(context, EventType.STAGE_STARTED, agent_call_id=agent_call_id)
        try:
            self._run_gates(self._gates.entry, context, agent_call_id)

            response = (
                self._execute_and_record_transcript(request, context, agent_call_id)
                if request.spec.requires_agent
                else NO_AGENT_RESPONSE
            )

            self._run_gates(self._gates.exit, context, agent_call_id)
        except StageGateFailure as exc:
            self._record(
                context,
                EventType.STAGE_FINISHED,
                agent_call_id=agent_call_id,
                payload={
                    "status": StageStatus.FAILED.value,
                    "outcome": "gate_failure",
                    "error": str(exc),
                },
            )
            raise

        status = (
            StageStatus.PASSED
            if response.outcome is AgentCallOutcome.SUCCESS
            else StageStatus.FAILED
        )
        if status is StageStatus.PASSED and self._artifacts_dir is not None:
            write_stage_artifacts(
                self._artifacts_dir,
                context.stage_id.value,
                request.workspace_path,
                response.files_written,
            )
        commit = (
            self._commit_hook(context, request.spec)
            if status is StageStatus.PASSED
            else None
        )
        self._record(
            context,
            EventType.STAGE_FINISHED,
            agent_call_id=agent_call_id,
            payload={
                "status": status.value,
                "outcome": response.outcome.value,
                "error": response.summary if status is StageStatus.FAILED else "",
            },
        )
        return StageRunResult(status=status, response=response, commit=commit)

    def _execute_and_record_transcript(
        self,
        request: StageRunRequest,
        context: StageContext,
        agent_call_id: str | None,
    ) -> AgentCallResponse:
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
        if (
            self._transcripts_dir is not None
            and request.spec.owner_profile
            and agent_call_id is not None
        ):
            write_transcript(
                self._transcripts_dir,
                AgentCallTranscript(
                    agent_call_id=agent_call_id,
                    run_id=context.run_id,
                    stage=context.stage_id.value,
                    attempt=context.attempt,
                    role=request.spec.owner_profile,
                    profile_version_hash=self._profile_version_hash(
                        request.spec.owner_profile
                    ),
                    prompt=request.rendered_prompt,
                    response=response,
                ),
            )
        return response

    def _profile_version_hash(self, profile_name: str) -> str | None:
        if self._profiles_root is None:
            return None
        try:
            return load_profile(
                self._profiles_root / f"{profile_name}.toml"
            ).version_hash
        except ConfigValidationError:
            return None

    def _run_gates(
        self, gates: Sequence[Gate], context: StageContext, agent_call_id: str | None
    ) -> None:
        for gate in gates:
            outcome = gate.check(context)
            self._record(
                context,
                EventType.GATE_RESULT,
                agent_call_id=agent_call_id,
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
        agent_call_id: str | None = None,
        payload: dict[str, object] | None = None,
    ) -> None:
        self._event_log.append(
            EventDraft(
                run_id=context.run_id,
                event_type=event_type,
                recorded_at=self._clock(),
                stage=context.stage_id.value,
                attempt=context.attempt,
                agent_call_id=agent_call_id,
                payload=payload or {},
            )
        )
