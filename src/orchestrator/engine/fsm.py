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

Real run.json creation (C1-AC2's "record") lives in the CLI layer
(`cli/commands/_common.py`), not here — it needs registry lookups the core
engine must stay independent of (CLAUDE.md: "core engine must not depend on
how agents are executed", and registry lookups are the same kind of
CLI-only concern).

**Known, documented gap (found wiring this):** requirements.md §11's own
directory picture nests every deliverable under `docs/requirements/<REQ-id>-
<slug>/` (`00-source.md`, `01-requirements.md`, ... `traceability.md` all
live there, one folder per requirement). Every piece of code that reads or
writes these files — `gates/traceability_gate.py`, `audit/traceability.py`,
every stage's mock fixtures, every agent profile's `output_contract` — was
already built against **flat, workspace-root filenames** instead, before
this task existed. Renaming that convention now would touch dozens of
already-tested files for a concern orthogonal to "wire the real executor";
this task keeps the flat convention everywhere (including the new
`00-source.md` writer below) rather than fixing half of it inconsistently.
Flagged in `docs/build-notes.md`'s integration-audit table, not silently
papered over.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path

from orchestrator.audit.agent_transcripts import write_transcript
from orchestrator.audit.approvals_log import append_approval
from orchestrator.audit.decisions_log import append_decision, next_decision_id
from orchestrator.audit.event_log import EventLog
from orchestrator.audit.metrics import compute_metrics, metrics_to_model
from orchestrator.audit.pr_description import generate_pr_description
from orchestrator.audit.report import generate_report
from orchestrator.audit.run_record import atomic_write_json, read_json
from orchestrator.audit.stage_artifacts import write_stage_artifacts
from orchestrator.audit.traceability import (
    CommitInfo,
    TraceabilityInputs,
    generate_traceability_report,
)
from orchestrator.config.schema import RetryLimits
from orchestrator.engine.graph import GRAPH
from orchestrator.engine.locking import acquire_lock, release_lock
from orchestrator.engine.plan_tasks import PlanTask, parse_fr_to_req, parse_plan_tasks
from orchestrator.engine.replanning import invalidate_from
from orchestrator.engine.runner import (
    NO_AGENT_RESPONSE,
    Clock,
    CommitHook,
    CommitTrailerContext,
    StageGates,
    StageRunner,
    StageRunnerOptions,
    StageRunRequest,
    StageRunResult,
    commit_message_with_trailers,
    no_op_commit,
    stage_commit_hook,
)
from orchestrator.engine.scheduler import BatchResult, run_batch
from orchestrator.exceptions import (
    GitCommandError,
    NoCheckpointRecordedError,
    NoPendingApprovalError,
    RunAlreadyTerminalError,
)
from orchestrator.executors.base import Executor
from orchestrator.gates.base import Gate, StageContext
from orchestrator.gates.command_gate import TestCoverageGate
from orchestrator.gates.existence_gate import ExistenceGate
from orchestrator.gates.schema_gate import SchemaGate
from orchestrator.gates.technology_stack_gate import TechnologyStackGate
from orchestrator.gates.traceability_gate import (
    DesignCitationGate,
    PlanCitationGate,
    RequirementsCitationGate,
)
from orchestrator.gates.unchanged_on_retry_gate import UnchangedOnRetryGate
from orchestrator.models.agent_io import (
    AgentCallOutcome,
    AgentCallRequest,
    AgentCallResponse,
    AgentCallTranscript,
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
from orchestrator.models.run import ExecutorKind, RunState
from orchestrator.policies.base import Policy, PolicyOutcome, compute_diff
from orchestrator.workspace.git_ops import (
    clone_repo,
    commit_all,
    commit_paths,
    current_commit_or_empty_tree,
    ensure_on_branch,
    init_repo,
    rollback_to,
    run_git,
)

GRAPH_STATE_FILENAME = "graph.json"
EVENTS_FILENAME = "events.jsonl"
APPROVALS_FILENAME = "approvals.jsonl"
DECISIONS_FILENAME = "decisions.jsonl"
METRICS_FILENAME = "metrics.json"
REPORT_FILENAME = "report.md"
PR_DESCRIPTION_FILENAME = "pr-description.md"
TRACEABILITY_FILENAME = "traceability.md"
SOURCE_BASELINE_FILENAME = "00-source.md"
DEFAULT_STAGE_TIMEOUT_SECONDS = 600
DEFAULT_STAGE_BUDGET_USD = 0.5
DEFAULT_TEMPLATE_PATH = Path("templates/python-service")
DEFAULT_PROFILES_ROOT = Path("agents/profiles")
TRANSCRIPTS_DIRNAME = "agents"
ARTIFACTS_DIRNAME = "artifacts"
VENV_CREATE_TIMEOUT_SECONDS = 120
PIP_INSTALL_TIMEOUT_SECONDS = 600
RUN_BRANCH_PREFIX = "run/"
DEFAULT_RETRY_LIMITS = RetryLimits(
    invalid_output_max_attempts=2,
    s6_failure_max_attempts=3,
    s7b_findings_max_attempts=2,
)
DEFAULT_MAX_AGENT_CALLS = 60


@dataclass(frozen=True)
class ReliabilityLimits:
    """The bounded-retry, safe-stop, and per-call numbers `drive()` enforces
    (T7.1; `per_call_timeout_seconds`/`budget_usd` added when config-driven
    limits were wired in ahead of T10 — previously hardcoded module
    constants, now `config/defaults.toml`'s own `limits.per_call_timeout_
    seconds`/`limits.max_call_budget_usd` via `cli/commands/_common.py`).
    """

    retry_limits: RetryLimits = field(default_factory=lambda: DEFAULT_RETRY_LIMITS)
    max_agent_calls: int = DEFAULT_MAX_AGENT_CALLS
    per_call_timeout_seconds: int = DEFAULT_STAGE_TIMEOUT_SECONDS
    budget_usd: float = DEFAULT_STAGE_BUDGET_USD


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

    `inject_fault`, `target_repo_url`, `base_ref`, `requirement_text`,
    `req_id`, `template_path` and `executor_kind` only matter the first time
    a run's GraphState is created — each is copied onto the matching
    `GraphState` field there and persists from then on, so `approve`/
    `reject`/`answer` re-entering `drive()` for an existing run don't need to
    (and can't easily) re-supply them — they read the persisted
    `GraphState.executor_kind` back instead (`engine.fsm.load_graph_state`)
    to reconstruct the *same* executor the run started with. Resolving
    `target_repo_url` (the registry lookup) and `requirement_text`/`req_id`/
    `base_ref` (the scenario config) is the CLI layer's job (`cli/commands/
    _common.py`) — `drive()` itself never touches the registry or scenario
    config files, only what's already been resolved into this request.

    `target_repo_url is None` means no real target is configured (the stub/
    test-graph case) — S0's commit hook then just adds `00-source.md` to
    whatever bare repo `drive()`'s preamble already set up, instead of
    cloning/copying a real workspace. `base_ref is None` (with a real
    target) means greenfield: copy `template_path` instead of cloning.
    """

    orch_home: Path
    project: str
    run_id: str
    scenario_id: str
    inject_fault: bool = False
    target_repo_url: str | None = None
    base_ref: str | None = None
    requirement_text: str = ""
    req_id: str = ""
    template_path: str | None = None
    executor_kind: ExecutorKind = ExecutorKind.MOCK

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
    exit-gate row); S1/S3/S4 get their real citation gate (T8.1, C10-AC1);
    S3 also gets the real technology-stack gate (item 6c); S6 gets the real
    command gate (D-11/AC5: tests pass, coverage >= threshold — `gates/
    command_gate.py`).
    """
    exit_gates: tuple[Gate, ...] = (SchemaGate(),)
    if stage_id is StageId.S2_CODEBASE_ANALYSIS:
        exit_gates = (*exit_gates, ExistenceGate())
    if stage_id is StageId.S3_DESIGN:
        exit_gates = (*exit_gates, TechnologyStackGate(), UnchangedOnRetryGate())
    if stage_id is StageId.S6_VERIFY:
        exit_gates = (*exit_gates, TestCoverageGate())
    traceability_gate = _traceability_gate_for(stage_id)
    if traceability_gate is not None:
        exit_gates = (*exit_gates, traceability_gate)
    return StageGates(entry=(SchemaGate(),), exit=exit_gates)


def _all_stages_passed(graph_state: GraphState) -> bool:
    return all(
        _is_satisfied(
            graph_state.stages.get(stage_id, StageResult(stage_id=stage_id)).status
        )
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


def _record_run_terminal(
    event_log: EventLog, run_id: str, terminal_state: RunState
) -> None:
    """C13-AC1: metrics are computed from events only. STOPPED/FAILED already
    get their own event (a `stop` event, from safe-stop/fallback-to-human);
    COMPLETED and REJECTED didn't get any event at all before this — this is
    that event, for whichever of the two just happened.
    """
    event_log.append(
        EventDraft(
            run_id=run_id,
            event_type=EventType.RUN_TERMINAL,
            recorded_at=datetime.now(UTC),
            payload={"terminal_state": terminal_state.value},
        )
    )


def _write_metrics_json(ref: RunRef, event_log: EventLog) -> None:
    """metrics.json, computed from this run's own events only (C13-AC1) —
    written at every terminal transition, whatever the outcome. STOPPED/
    FAILED already have their own `stop` event by the time this runs;
    COMPLETED/REJECTED get `_record_run_terminal`'s `run_terminal` event
    first, so either way this reads the full, final event list.
    """
    metrics = compute_metrics(event_log.read_all())
    directory = run_dir(ref.orch_home, ref.project, ref.run_id)
    atomic_write_json(directory / METRICS_FILENAME, metrics_to_model(metrics))


def _write_traceability(ref: RunRef, graph_state: GraphState) -> None:
    """traceability.md (C10-AC3), written into the workspace once a run
    reaches COMPLETED — any other outcome would mostly just report gaps
    against an unfinished chain, not the FR->...->test table it's meant to
    show, so only COMPLETED gets one.
    """
    workspace = workspace_dir(ref.orch_home, ref.project, ref.run_id)

    def _read(name: str) -> str:
        path = workspace / name
        return path.read_text(encoding="utf-8") if path.is_file() else ""

    acceptance_dir = workspace / "tests" / "acceptance"
    acceptance_test_files = (
        {
            path.relative_to(workspace).as_posix(): path.read_text(encoding="utf-8")
            for path in sorted(acceptance_dir.rglob("*.py"))
        }
        if acceptance_dir.is_dir()
        else {}
    )
    commits = tuple(
        CommitInfo(sha=sha)
        for result in graph_state.stages.values()
        for sha in result.commits
    )
    report = generate_traceability_report(
        TraceabilityInputs(
            requirements_md=_read("01-requirements.md"),
            design_md=_read("02-design.md"),
            plan_md=_read("03-plan.md"),
            commits=commits,
            acceptance_test_files=acceptance_test_files,
        )
    )
    (workspace / TRACEABILITY_FILENAME).write_text(report, encoding="utf-8")


def _finalize_completed_run(
    ref: RunRef, graph_state: GraphState, event_log: EventLog
) -> None:
    _record_run_terminal(event_log, ref.run_id, RunState.COMPLETED)
    _write_metrics_json(ref, event_log)
    _write_traceability(ref, graph_state)


def _complete_and_record(
    graph_state: GraphState, event_log: EventLog, ref: RunRef
) -> None:
    """`_complete_if_all_stages_passed`, plus recording the transition and
    writing this run's terminal artifacts (metrics.json, traceability.md)."""
    was_incomplete = graph_state.terminal_state is None
    _complete_if_all_stages_passed(graph_state)
    if was_incomplete and graph_state.terminal_state is RunState.COMPLETED:
        _finalize_completed_run(ref, graph_state, event_log)


_SATISFIED_STATUSES = (StageStatus.PASSED, StageStatus.SKIPPED)


def _is_satisfied(status: StageStatus) -> bool:
    """C4-AC3: S2 skipped for greenfield still satisfies anything depending
    on it ("S3 treats SKIPPED as satisfied") — SKIPPED counts alongside
    PASSED everywhere a stage's own completion is checked."""
    return status in _SATISFIED_STATUSES


def _next_ready_batch(graph_state: GraphState) -> tuple[StageSpec, ...]:
    """Every not-yet-satisfied stage whose dependencies are all satisfied.

    Usually one stage; two when a pair of parallel siblings (S5a+S5b, S7a+S7b)
    both become ready at once, since both depend on the same upstream stage
    (T6.1) rather than chaining — the batch size follows purely from the
    graph's shape, nothing here hardcodes which stages pair up.
    """
    ready = []
    for stage_id, spec in GRAPH.items():
        result = graph_state.stages.get(stage_id)
        if result is not None and _is_satisfied(result.status):
            continue
        if all(
            _is_satisfied(graph_state.stages.get(dep, StageResult(stage_id=dep)).status)
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
        target_repo_url=request.target_repo_url,
        base_ref=request.base_ref,
        requirement_text=request.requirement_text,
        req_id=request.req_id,
        template_path=request.template_path,
        executor_kind=request.executor_kind,
    )


def _load_existing_graph_state(ref: RunRef) -> GraphState:
    """Load state for a run that must already exist (resolve_checkpoint/stop_run)."""
    return read_json(_state_path(ref), GraphState)


def load_graph_state(ref: RunRef) -> GraphState:
    """Public read-only peek at a run's current state — the CLI layer's one
    way to recover which executor/target a run started with (persisted onto
    `GraphState` the first time `drive()` creates it) before re-entering
    `drive()`/`resolve_checkpoint()` for `approve`/`reject`/`answer`, without
    duplicating graph.json's read path.
    """
    return _load_existing_graph_state(ref)


@dataclass(frozen=True)
class _LoopResources:
    """What every iteration of drive()'s loop needs, computed once per call."""

    ref: RunRef
    executor: Executor
    event_log: EventLog
    workspace: Path
    max_run_duration_seconds: float
    reliability: ReliabilityLimits = DEFAULT_RELIABILITY_LIMITS
    profiles_root: Path = DEFAULT_PROFILES_ROOT
    transcripts_dir: Path | None = None
    artifacts_dir: Path | None = None


def _build_runner(
    resources: _LoopResources, graph_state: GraphState, spec: StageSpec
) -> StageRunner:
    if spec.stage_id is StageId.S2_CODEBASE_ANALYSIS and graph_state.base_ref is None:
        return _SkippedS2Runner(
            executor=resources.executor,
            event_log=resources.event_log,
            clock=lambda: datetime.now(UTC),
        )
    if spec.commit_strategy is CommitStrategy.ONE_PER_TASK:
        return _PerTaskS5aRunner(
            executor=resources.executor,
            event_log=resources.event_log,
            clock=lambda: datetime.now(UTC),
            run_id=resources.ref.run_id,
            options=StageRunnerOptions(
                profiles_root=resources.profiles_root,
                transcripts_dir=resources.transcripts_dir,
                artifacts_dir=resources.artifacts_dir,
            ),
        )
    return StageRunner(
        executor=resources.executor,
        event_log=resources.event_log,
        clock=lambda: datetime.now(UTC),
        options=StageRunnerOptions(
            gates=_gates_for(spec.stage_id),
            commit_hook=_commit_hook_for(spec.stage_id, resources, graph_state),
            profiles_root=resources.profiles_root,
            transcripts_dir=resources.transcripts_dir,
            artifacts_dir=resources.artifacts_dir,
        ),
    )


def _commit_hook_for(
    stage_id: StageId, resources: _LoopResources, graph_state: GraphState
) -> CommitHook:
    """S0/S8 need the orchestrator's own real work (workspace prep + `00-
    source.md`; report.md/pr-description.md generation) done at the point
    their commit hook fires — every other stage keeps the generic one-
    commit-per-stage hook (T6.1)."""
    if stage_id is StageId.S0_PREPARE:
        return _s0_commit_hook(resources, graph_state)
    if stage_id is StageId.S8_RELEASE:
        return _s8_commit_hook(resources, graph_state)
    return stage_commit_hook


S2_SKIP_REASON = "greenfield run: no existing codebase to analyze (C4-AC3)"


class _SkippedS2Runner(StageRunner):
    """S2 skipped for greenfield (C4-AC3: "S2 skipped with reason for
    greenfield; always runs otherwise"). No `base_ref` means there's no
    existing codebase at all to analyze — `engine/fsm.py`'s own
    `_build_runner` is what routes S2 here, keyed on `graph_state.base_ref
    is None`, so a brownfield run (real `base_ref`) still gets the standard
    `StageRunner` and a real analyst call. Marks the stage SKIPPED, not
    PASSED, so it's visibly distinct in graph.json/report.md; `_is_satisfied`
    treats SKIPPED the same as PASSED everywhere a stage's own completion is
    checked, so S3 still becomes ready right after.
    """

    def run(self, request: StageRunRequest) -> StageRunResult:
        context = StageContext(
            run_id=request.run_id,
            stage_id=request.spec.stage_id,
            attempt=request.attempt,
            workspace_path=request.workspace_path,
        )
        self._record(context, EventType.STAGE_STARTED)
        self._record(
            context,
            EventType.STAGE_FINISHED,
            payload={"status": StageStatus.SKIPPED.value, "reason": S2_SKIP_REASON},
        )
        return StageRunResult(
            status=StageStatus.SKIPPED, response=NO_AGENT_RESPONSE, commit=None
        )


def _prepare_real_workspace(
    workspace: Path,
    target_repo_url: str,
    base_ref: str | None,
    template_path: str | None,
) -> None:
    """Copy the greenfield template, or clone the target at `base_ref`, into
    `workspace` (still empty at this point — see `drive()`'s preamble) —
    D-5/D-21's real S0 prepare logic (workspace/manager.py's own functions
    aren't reused here: they each make their own commit immediately, which
    would leave two commits for S0 instead of the one `CommitStrategy.ONE`
    promises; `00-source.md` needs to land in that same single commit).
    """
    if base_ref is None:
        template = Path(template_path or str(DEFAULT_TEMPLATE_PATH))
        shutil.copytree(template, workspace, dirs_exist_ok=True)
        init_repo(workspace)
        run_git(workspace, "remote", "add", "origin", target_repo_url)
    else:
        clone_repo(Path(target_repo_url), workspace, base_ref)


def _create_workspace_venv(workspace: Path) -> None:
    """`python -m venv .venv` + `pip install -e ".[dev]"` — S5a/S5b's real
    `Bash(python -m pytest *)` calls and S6's real command gate both need a
    real venv with the workspace's own dev dependencies installed (C3-AC3;
    T5.1's build notes flagged this as "deferred... needed at T10" — this is
    that). Best-effort: only runs when the workspace declares a `[project.
    optional-dependencies] dev` group at all (`pyproject.toml` present);
    skipped otherwise rather than failing S0 outright for a workspace with
    no such convention.
    """
    if not (workspace / "pyproject.toml").is_file():
        return
    venv_dir = workspace / ".venv"
    subprocess.run(  # noqa: S603
        [sys.executable, "-m", "venv", str(venv_dir)],
        cwd=str(workspace),
        check=True,
        timeout=VENV_CREATE_TIMEOUT_SECONDS,
        capture_output=True,
    )
    bin_dir = venv_dir / ("Scripts" if sys.platform == "win32" else "bin")
    python = bin_dir / ("python.exe" if sys.platform == "win32" else "python")
    subprocess.run(  # noqa: S603
        [str(python), "-m", "pip", "install", "-e", ".[dev]"],
        cwd=str(workspace),
        check=True,
        timeout=PIP_INSTALL_TIMEOUT_SECONDS,
        capture_output=True,
    )


def _s0_commit_hook(resources: _LoopResources, graph_state: GraphState) -> CommitHook:
    def hook(_context: StageContext, spec: StageSpec) -> str | None:
        workspace = resources.workspace
        target_repo_url = graph_state.target_repo_url
        if target_repo_url is not None:
            _prepare_real_workspace(
                workspace,
                target_repo_url,
                graph_state.base_ref,
                graph_state.template_path,
            )
            ensure_on_branch(workspace, f"{RUN_BRANCH_PREFIX}{resources.ref.run_id}")
            _create_workspace_venv(workspace)
        (workspace / SOURCE_BASELINE_FILENAME).write_text(
            (graph_state.requirement_text or "") + "\n", encoding="utf-8"
        )
        message = commit_message_with_trailers(
            "S0: workspace prepared",
            CommitTrailerContext(
                run_id=resources.ref.run_id, stage_label=spec.stage_id.value
            ),
        )
        return commit_all(workspace, message)

    return hook


def _s8_commit_hook(resources: _LoopResources, graph_state: GraphState) -> CommitHook:
    def hook(_context: StageContext, _spec: StageSpec) -> str | None:
        directory = run_dir(
            resources.ref.orch_home, resources.ref.project, resources.ref.run_id
        )
        metrics = compute_metrics(resources.event_log.read_all())
        (directory / REPORT_FILENAME).write_text(
            generate_report(graph_state, metrics), encoding="utf-8"
        )
        (directory / PR_DESCRIPTION_FILENAME).write_text(
            generate_pr_description(graph_state, run_record_location=str(directory)),
            encoding="utf-8",
        )
        return None  # S8's commit_strategy is NONE: nothing to commit in the workspace

    return hook


def _plan_tasks(workspace_path: Path) -> tuple[PlanTask, ...]:
    plan_path = workspace_path / "03-plan.md"
    if not plan_path.is_file():
        return ()
    return parse_plan_tasks(plan_path.read_text(encoding="utf-8"))


def _fr_to_req(workspace_path: Path) -> dict[str, str]:
    requirements_path = workspace_path / "01-requirements.md"
    if not requirements_path.is_file():
        return {}
    return parse_fr_to_req(requirements_path.read_text(encoding="utf-8"))


def _already_committed_tasks(workspace: Path) -> dict[str, str]:
    """task_id -> commit sha, for every commit on this branch already
    carrying a `Task: <id>` trailer — item 5, T9.9: a real run's S5a retry
    (attempt 2, after attempt 1's T-1.1 succeeded and committed, then T-1.2
    failed) redid T-1.1 from scratch instead of resuming after it. The
    per-task loop below skips any task found here rather than re-calling
    the agent for work that already landed.
    """
    try:
        log = run_git(workspace, "log", "--format=%H %(trailers:key=Task,valueonly)")
    except GitCommandError:
        return {}
    result: dict[str, str] = {}
    for line in log.splitlines():
        parts = line.strip().split(maxsplit=1)
        if len(parts) == 2:
            sha, task_id = parts
            result.setdefault(task_id, sha)
    return result


def _task_prompt(task: PlanTask) -> str:
    return (
        f"Implement plan task {task.task_id} (cites {task.dd_id}, under "
        f"{task.fr_id}): {task.description}\n\nOnly touch the files this "
        "task calls for. Do not implement any other task from 03-plan.md in "
        "this call — each task gets its own call and its own commit."
    )


class _PerTaskS5aRunner(StageRunner):
    """S5a: one developer call per 03-plan.md task, in plan order, each
    committed separately with Task/FR/Req/Run/Stage trailers (C10-AC2, D-8,
    requirements.md §12's "per-task commits"). `engine/fsm.py`'s own
    `_build_runner` is what routes a stage here — keyed on `StageSpec.
    commit_strategy is ONE_PER_TASK`, not on `stage_id`, so a test's bespoke
    S5a stub spec (a different `commit_strategy`, same `StageId.
    S5A_IMPLEMENT`) still gets the standard single-call `StageRunner`
    unaffected — the same reasoning as `requires_agent` not being keyed on
    `owner_profile` (see `StageSpec`'s own docstring).

    No entry/exit gates: S5a's only configured gate is the stub `SchemaGate`
    (always passes trivially), not worth threading through N per-task calls.
    S4's own exit gate (`PlanCitationGate`, T8.1) already guarantees
    03-plan.md has at least one well-formed task under every FR by the time
    S5a ever runs in the real graph — `_no_tasks_result` below is a safety
    net for a malformed/missing plan, not a path the real graph can reach.
    """

    def __init__(
        self,
        executor: Executor,
        event_log: EventLog,
        clock: Clock,
        run_id: str,
        options: StageRunnerOptions | None = None,
    ) -> None:
        super().__init__(
            executor=executor, event_log=event_log, clock=clock, options=options
        )
        self._run_id = run_id

    def run(self, request: StageRunRequest) -> StageRunResult:
        context = StageContext(
            run_id=request.run_id,
            stage_id=request.spec.stage_id,
            attempt=request.attempt,
            workspace_path=request.workspace_path,
        )
        self._record(context, EventType.STAGE_STARTED)

        tasks = _plan_tasks(request.workspace_path)
        if not tasks:
            return self._no_tasks_result(context)

        fr_to_req = _fr_to_req(request.workspace_path)
        already_done = _already_committed_tasks(request.workspace_path)
        commits: list[str] = []
        response = NO_AGENT_RESPONSE
        for task in tasks:
            if task.task_id in already_done:
                commits.append(already_done[task.task_id])
                continue
            agent_call_id = f"{context.stage_id.value}-{context.attempt}-{task.task_id}"
            response = self._executor.execute(
                AgentCallRequest(
                    profile_name=request.spec.owner_profile or "",
                    scenario_id=request.scenario_id,
                    stage=request.spec.stage_id.value,
                    attempt=request.attempt,
                    task_id=task.task_id,
                    rendered_prompt=_task_prompt(task),
                    workspace_path=str(request.workspace_path),
                    timeout_seconds=request.timeout_seconds,
                    budget_usd=request.budget_usd,
                )
            )
            if self._transcripts_dir is not None and request.spec.owner_profile:
                write_transcript(
                    self._transcripts_dir,
                    AgentCallTranscript(
                        agent_call_id=agent_call_id,
                        run_id=context.run_id,
                        stage=context.stage_id.value,
                        attempt=context.attempt,
                        task_id=task.task_id,
                        role=request.spec.owner_profile,
                        profile_version_hash=self._profile_version_hash(
                            request.spec.owner_profile
                        ),
                        prompt=_task_prompt(task),
                        response=response,
                    ),
                )
            if (
                self._artifacts_dir is not None
                and response.outcome is AgentCallOutcome.SUCCESS
            ):
                write_stage_artifacts(
                    self._artifacts_dir,
                    context.stage_id.value,
                    request.workspace_path,
                    response.files_written,
                )
            if response.outcome is not AgentCallOutcome.SUCCESS:
                self._record(
                    context,
                    EventType.STAGE_FINISHED,
                    payload={
                        "status": StageStatus.FAILED.value,
                        "outcome": response.outcome.value,
                        "error": response.summary,
                    },
                )
                return StageRunResult(
                    status=StageStatus.FAILED,
                    response=response,
                    commit=commits[-1] if commits else None,
                    commits=tuple(commits),
                )
            message = commit_message_with_trailers(
                f"{task.task_id}: {task.description}",
                CommitTrailerContext(
                    run_id=self._run_id,
                    stage_label=request.spec.stage_id.value,
                    task_id=task.task_id,
                    fr_id=task.fr_id,
                    req_id=fr_to_req.get(task.fr_id),
                ),
            )
            commits.append(
                commit_paths(request.workspace_path, response.files_written, message)
            )

        self._record(
            context,
            EventType.STAGE_FINISHED,
            payload={
                "status": StageStatus.PASSED.value,
                "outcome": response.outcome.value,
                "error": "",
            },
        )
        return StageRunResult(
            status=StageStatus.PASSED,
            response=response,
            commit=commits[-1] if commits else None,
            commits=tuple(commits),
        )

    def _no_tasks_result(self, context: StageContext) -> StageRunResult:
        response = AgentCallResponse(
            outcome=AgentCallOutcome.INVALID_OUTPUT,
            summary="03-plan.md has no parseable tasks",
            duration_seconds=0.0,
        )
        self._record(
            context,
            EventType.STAGE_FINISHED,
            payload={
                "status": StageStatus.FAILED.value,
                "outcome": response.outcome.value,
                "error": response.summary,
            },
        )
        return StageRunResult(status=StageStatus.FAILED, response=response, commit=None)


# Stage-specific task instructions (what to do *this call*), on top of the
# profile's own role/format rules (agents/profiles/*.toml) — the profile
# says how a role writes 01-requirements.md/etc.; this says which files to
# read as input and what today's actual ask is. S0/S6/S8 need none of this
# (requires_agent=False, orchestrator-only).
_STAGE_TASKS: dict[StageId, str] = {
    StageId.S2_CODEBASE_ANALYSIS: (
        "Analyze the existing codebase already checked out in this workspace "
        "and write 02-impact-analysis.md per your S2 responsibilities."
    ),
    StageId.S3_DESIGN: (
        "Read 01-requirements.md (and 02-impact-analysis.md, if present) and "
        "write 02-design.md."
    ),
    StageId.S4_PLAN: "Read 01-requirements.md and 02-design.md and write 03-plan.md.",
    StageId.S5A_IMPLEMENT: (
        "Read 03-plan.md. Implement every task listed there in this single "
        "call, plus unit tests for each (per-task looping isn't wired into "
        "the orchestrator yet, so this call covers the whole plan, not one "
        "task)."
    ),
    StageId.S5B_ACCEPTANCE_TESTS: (
        "Read 03-plan.md's acceptance criteria and 02-design.md's contracts "
        "(not src/) and write the acceptance tests."
    ),
    StageId.S7A_DOCS: (
        "Read 03-plan.md and the changes under src/ from this run, and "
        "document every changed API surface."
    ),
    StageId.S7B_REVIEW: (
        "Review the changes under src/ and tests/ from this run against "
        "02-design.md and 03-plan.md; write the findings report."
    ),
}


def _technology_stack_instruction(workspace: Path) -> str:
    """The target's real technology stack (item 6b, C4/§12) — read straight
    from the workspace's own pyproject.toml, which is already the right one
    by the time S3 runs (S0's own commit hook either copied it from the
    greenfield template or cloned it from the existing target), so the
    architect never has to guess a language/framework instead of reading
    what's actually there. Falls back to naming the template's own stack
    (Python 3.11+) only when there's genuinely no pyproject.toml to read —
    a bare/no-target workspace (stub graphs, most unit tests).
    """
    pyproject_path = workspace / "pyproject.toml"
    if pyproject_path.is_file():
        content = pyproject_path.read_text(encoding="utf-8")
        return (
            "Use this project's existing technology stack — do not "
            "introduce a new language or framework. Its pyproject.toml:\n\n"
            f"{content}"
        )
    return (
        "No pyproject.toml was found in the workspace; use Python 3.11+ "
        "with a standard HTTP framework and test client, matching the "
        "approved greenfield template's own stack."
    )


def _rendered_prompt_for(
    spec: StageSpec, graph_state: GraphState, workspace: Path
) -> str:
    if spec.stage_id is StageId.S1_REQUIREMENTS:
        prompt = (
            f"Requirement {graph_state.req_id}: {graph_text}"
            if (graph_text := graph_state.requirement_text)
            else f"Requirement {graph_state.req_id}"
        )
        if graph_state.clarification_answer:
            # T7.4: S1 re-running after a Clarification answer gets that
            # answer as additional context.
            prompt += (
                f"\n\nHuman answer to blocking questions: "
                f"{graph_state.clarification_answer}"
            )
        return prompt
    prompt = _STAGE_TASKS.get(spec.stage_id, f"stage {spec.stage_id.value}")
    if spec.stage_id is StageId.S3_DESIGN:
        prompt += f"\n\n{_technology_stack_instruction(workspace)}"
        if graph_state.design_rejection_feedback:
            # C11-AC1: the re-run after a Design rejection must actually
            # receive the human's feedback (item 5/T9.7 — found missing
            # entirely while diagnosing a real run: the previous design was
            # never revised because the re-run got the exact same prompt as
            # the first attempt, with no signal anything needed to change).
            prompt += (
                "\n\nThis design was REJECTED by a human reviewer with this "
                f"feedback — revise 02-design.md to address it:\n"
                f"{graph_state.design_rejection_feedback}"
            )
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
        rendered_prompt=_rendered_prompt_for(spec, graph_state, resources.workspace),
        timeout_seconds=resources.reliability.per_call_timeout_seconds,
        budget_usd=resources.reliability.budget_usd,
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
        _write_metrics_json(resources.ref, resources.event_log)
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
    _write_metrics_json(resources.ref, resources.event_log)


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
        options=StageRunnerOptions(
            gates=StageGates(),
            commit_hook=no_op_commit,
            profiles_root=resources.profiles_root,
            transcripts_dir=resources.transcripts_dir,
        ),
    )
    result = runner.run(
        StageRunRequest(
            spec=fix_spec,
            run_id=resources.ref.run_id,
            scenario_id=graph_state.scenario_id,
            workspace_path=resources.workspace,
            rendered_prompt=subject,
            timeout_seconds=resources.reliability.per_call_timeout_seconds,
            budget_usd=resources.reliability.budget_usd,
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
    batch_result: BatchResult,
    attempts: int,
    retry_limits: RetryLimits,
) -> None:
    """A stage's own agent call failed (invalid output / error / timeout, or a
    gate rejected its output). S6 gets a fix call before its next attempt
    (G-13), given the real gate failure output (`batch_result.result.
    response.summary` — a gate-raised `StageGateFailure`'s own `str()`,
    which for the real command gate is `scripts/check.py`'s own exit code +
    output tail) so a real developer agent has something concrete to act
    on, not just a generic "fix it" instruction; every other stage
    (including S7b failing outright, as opposed to passing with findings —
    handled separately) just retries the same call — it stays FAILED here
    and `_next_ready_batch` naturally re-selects it next iteration, since a
    FAILED stage is never treated as already-passed.
    """
    spec = batch_result.spec
    max_attempts = _max_attempts_for(spec.stage_id, retry_limits)
    # Attempts *since this stage's current retry cycle began* (T9.7/item 1) —
    # `attempts` itself is the stage's whole-run total, used unchanged for
    # event/fixture keying, but a rejection or Clarification answer
    # (engine/replanning.py:invalidate_from) starts a fresh bounded-retry
    # budget, so counting from the run's start here would let old, unrelated
    # attempts eat into what should be a full allowance for the re-plan.
    cycle_start = graph_state.retry_cycle_start_attempts.get(spec.stage_id, 0)
    attempts_this_cycle = attempts - cycle_start
    if attempts_this_cycle >= max_attempts:
        _fallback_to_human(
            resources,
            graph_state,
            spec.stage_id,
            attempts,
            f"{spec.stage_id.value} failed after {attempts_this_cycle} attempt(s) "
            f"this retry cycle ({attempts} total)",
        )
        return
    _record_automatic_retry(resources, spec.stage_id, attempts)
    if spec.stage_id is StageId.S6_VERIFY:
        subject = (
            "S5a-fix: address S6 verification failure\n\n"
            f"{batch_result.result.response.summary}"
        )
        _run_fix_call(resources, graph_state, subject, attempts)


def _record_automatic_retry(
    resources: _LoopResources, stage_id: StageId, attempts: int
) -> None:
    """T9.7/item 8: found on a real run's own metrics.json — retry_count
    only ever counted a design-rejection/Clarification re-plan (the only two
    places that emitted a RETRY event); an ordinary bounded-retry re-attempt
    (a stage fails, then automatically tries again) recorded no event at
    all, so `retry_count` silently undercounted the far more common case.
    """
    resources.event_log.append(
        EventDraft(
            run_id=resources.ref.run_id,
            event_type=EventType.RETRY,
            recorded_at=datetime.now(UTC),
            stage=stage_id.value,
            attempt=attempts,
            payload={"trigger": "automatic_retry"},
        )
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


def _flip_return_true(match: re.Match[str]) -> str:
    return "return False"


def _flip_return_false(match: re.Match[str]) -> str:
    return "return True"


def _flip_equality(match: re.Match[str]) -> str:
    return "!="


# Small, deliberately conservative set of mutations (G-16) — each one is a
# real behavior change an existing unit/acceptance test plausibly already
# covers, not a syntax break or an unconditional failure. First match wins;
# `_find_fault_mutation` scans every src/ file (sorted, for determinism).
FAULT_MUTATION_PATTERNS: tuple[
    tuple[re.Pattern[str], Callable[[re.Match[str]], str]], ...
] = (
    (re.compile(r"\breturn True\b"), _flip_return_true),
    (re.compile(r"\breturn False\b"), _flip_return_false),
    (re.compile(r"(?<![=!<>])==(?!=)"), _flip_equality),
)


@dataclass(frozen=True)
class _FaultMutation:
    """One found-and-applied small defect: enough to write it, commit it,
    and record exactly what changed (G-16's own "record exactly what was
    changed" requirement)."""

    path: Path
    mutated_content: str
    description: str


def _find_fault_mutation(workspace: Path) -> _FaultMutation | None:
    src_dir = workspace / "src"
    if not src_dir.is_dir():
        return None
    for path in sorted(src_dir.rglob("*.py")):
        content = path.read_text(encoding="utf-8")
        for pattern, replace in FAULT_MUTATION_PATTERNS:
            match = pattern.search(content)
            if match is None:
                continue
            replacement = replace(match)
            mutated = content[: match.start()] + replacement + content[match.end() :]
            description = f"{match.group(0)!r} -> {replacement!r}"
            return _FaultMutation(
                path=path, mutated_content=mutated, description=description
            )
    return None


def _inject_fault(resources: _LoopResources, graph_state: GraphState) -> None:
    """G-16: right after S5a passes, mutate one small, real behavior in a
    file S5a itself wrote under src/ — a change the run's own existing
    unit/acceptance tests genuinely catch, rather than an unconditional
    failure nothing could ever fix (the previous design: a standalone
    `tests/acceptance/` file that always raised, which the developer fix
    call couldn't even write to — test_engineer's path, not developer's —
    so the retry could never actually pass). S6's very next attempt then
    runs completely normally; its real command gate (gates/command_gate.py)
    fails attempt 1 for real, and the fix call gets that real failure output
    to work from (`_handle_stage_failure`).

    `injected` (a first-class `EventDraft` field, not buried in payload)
    keeps this event trivially distinguishable from an organic failure in
    `events.jsonl`. `graph_state.fault_injected` is still set even when no
    mutatable pattern is found (nothing to retry for — G-16 stays a no-op
    for that run rather than silently retrying forever).
    """
    mutation = _find_fault_mutation(resources.workspace)
    graph_state.fault_injected = True
    if mutation is None:
        return
    mutation.path.write_text(mutation.mutated_content, encoding="utf-8")
    relative_path = mutation.path.relative_to(resources.workspace).as_posix()
    message = commit_message_with_trailers(
        f"G-16: injected fault ({relative_path})",
        CommitTrailerContext(
            run_id=resources.ref.run_id, stage_label="fault-injection"
        ),
    )
    commit_paths(resources.workspace, (relative_path,), message)
    resources.event_log.append(
        EventDraft(
            run_id=resources.ref.run_id,
            event_type=EventType.FAULT_INJECTED,
            recorded_at=datetime.now(UTC),
            stage=StageId.S5A_IMPLEMENT.value,
            payload={"file": relative_path, "change": mutation.description},
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
        spec.stage_id is StageId.S5A_IMPLEMENT
        and result.status is StageStatus.PASSED
        and graph_state.inject_fault
        and not graph_state.fault_injected
    )
    if should_inject:
        # G-16: mutate a small, real behavior S5a just implemented, right
        # after S5a itself passes — S6's own next attempt then runs
        # completely normally and its real command gate (gates/
        # command_gate.py) catches the mutation for real, no synthetic
        # override needed (see _inject_fault's own docstring).
        _inject_fault(resources, graph_state)

    graph_state.stages[spec.stage_id] = StageResult(
        stage_id=spec.stage_id,
        status=result.status,
        attempts=attempts,
        commits=result.commits or ((result.commit,) if result.commit else ()),
    )
    graph_state.agent_call_count += 1
    if result.status is StageStatus.PASSED:
        graph_state.last_checkpoint_commit = current_commit_or_empty_tree(
            resources.workspace
        )
        if spec.stage_id is StageId.S0_PREPARE and graph_state.base_commit is None:
            # Captured once S0 actually finishes (not in drive()'s preamble
            # any more — a real target's workspace doesn't have its base
            # commit until S0's own commit hook clones/copies it in), so
            # every S6 policy check diffs the run's own changes, never the
            # target repo's entire history.
            graph_state.base_commit = graph_state.last_checkpoint_commit

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
    elif result.status is StageStatus.FAILED:
        _handle_stage_failure(
            resources, graph_state, batch_result, attempts, retry_limits
        )
    elif spec.stage_id is StageId.S6_VERIFY:
        if not _evaluate_s6_policies(resources, graph_state, policies):
            _complete_and_record(graph_state, resources.event_log, resources.ref)
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
        _complete_and_record(graph_state, resources.event_log, resources.ref)


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
        workspace.mkdir(parents=True, exist_ok=True)
        workspace_has_git = (workspace / ".git").exists()
        if not workspace_has_git and graph_state.target_repo_url is None:
            # No real target configured (stub/test graphs) — bare fallback so
            # any commit-bearing stage still has *a* repo to work with. With a
            # real target, S0's own commit hook does the real clone/template-
            # copy instead — it needs `workspace` to still be empty (git clone
            # refuses a non-empty destination), so this must NOT run first.
            init_repo(workspace)
            workspace_has_git = True
        if workspace_has_git:
            # D-5: create/switch to the run branch before any stage executes,
            # so the run is never left on main. Skipped on a real target's
            # very first call — nothing to switch branches on until S0's own
            # commit hook (below, inside the loop) has cloned/copied in.
            ensure_on_branch(workspace, f"{RUN_BRANCH_PREFIX}{ref.run_id}")
        s0_spec = GRAPH.get(StageId.S0_PREPARE)
        s0_is_orchestrator_only = s0_spec is not None and not s0_spec.requires_agent
        if not s0_is_orchestrator_only and graph_state.base_commit is None:
            # The real S0 (requires_agent=False) writes 00-source.md (and, for
            # a real target, clones/copies the whole workspace) as pure
            # infrastructure, not diffable agent work — base_commit is
            # captured the other way for it, after it finishes
            # (_record_batch_result, once it PASSES). A *stub* graph's S0 (any
            # test not reusing the real spec, requires_agent defaulting True)
            # is a normal, executor-backed stage instead, so its own commit
            # must stay *inside* the diffable range — captured here, before
            # it runs, same as the bare repo's current state (empty tree, the
            # first time).
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
            reliability=reliability,
            transcripts_dir=(
                run_dir(ref.orch_home, ref.project, ref.run_id) / TRANSCRIPTS_DIRNAME
            ),
            artifacts_dir=(
                run_dir(ref.orch_home, ref.project, ref.run_id) / ARTIFACTS_DIRNAME
            ),
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
                build_runner=lambda spec: _build_runner(resources, graph_state, spec),
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
            _record_run_terminal(event_log, ref.run_id, RunState.REJECTED)
            _write_metrics_json(ref, event_log)
        elif (
            decision is ApprovalDecision.REJECT
            and checkpoint is ApprovalCheckpointKind.DESIGN
        ):
            # C11: reject Design with feedback -> re-run S3 (with the
            # feedback) then S4 onward; S1/S2 are upstream of S3, so they're
            # left untouched. Downstream stages are marked invalidated, not
            # re-run directly here — the existing batch-selection machinery
            # (engine/fsm.py's drive() loop) re-selects anything not PASSED.
            # C11-AC1 requires the re-run to actually receive the feedback —
            # persisted here so _rendered_prompt_for can include it in S3's
            # next call (found missing entirely while diagnosing a real run,
            # item 5/T9.7: the comment was recorded to approvals.jsonl but
            # never reached the agent).
            graph_state.design_rejection_feedback = comment
            invalidated = invalidate_from(graph_state, StageId.S3_DESIGN)
            decisions_path = (
                run_dir(ref.orch_home, ref.project, ref.run_id) / DECISIONS_FILENAME
            )
            append_decision(
                decisions_path,
                Decision(
                    decision_id=next_decision_id(decisions_path, ref.run_id),
                    stage=StageId.S3_DESIGN.value,
                    actor=approver,
                    choice="reject",
                    rationale=comment,
                    recorded_at=now,
                ),
            )
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
            _complete_and_record(graph_state, event_log, ref)
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
        _write_metrics_json(ref, event_log)
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
