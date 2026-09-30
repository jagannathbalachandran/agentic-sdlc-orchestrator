"""Stage graph domain models: StageSpec, StageStatus, GraphState.

The graph itself (which StageSpecs exist and how they're wired) lives in
engine/graph.py; these are just the data shapes (architecture-proposal.md §3.1).
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from orchestrator.models.approvals import ApprovalCheckpointKind
from orchestrator.models.run import RunState


class StageId(StrEnum):
    """The fixed Phase 1 stage graph (requirements.md §7)."""

    S0_PREPARE = "S0"
    S1_REQUIREMENTS = "S1"
    S2_CODEBASE_ANALYSIS = "S2"
    S3_DESIGN = "S3"
    S4_PLAN = "S4"
    S5A_IMPLEMENT = "S5a"
    S5B_ACCEPTANCE_TESTS = "S5b"
    S6_VERIFY = "S6"
    S7A_DOCS = "S7a"
    S7B_REVIEW = "S7b"
    S8_RELEASE = "S8"


class StageStatus(StrEnum):
    """Per-stage status recorded in graph.json."""

    PENDING = "pending"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    INVALIDATED = "invalidated"


class CommitStrategy(StrEnum):
    """How many commits a stage makes (requirements.md §7 stage table)."""

    NONE = "none"
    ONE = "one"
    ONE_PER_TASK = "one_per_task"


class StageSpec(BaseModel):
    """Declarative descriptor for one stage in the fixed Phase 1 graph.

    `requires_agent` (default `True`) is distinct from `owner_profile` being
    set: S0/S6/S8 are orchestrator-only (workspace prep / gates + policies /
    release checkpoint) and must never reach the executor at all — under the
    real executor, an empty `profile_name` would try to load a profile file
    that doesn't exist. `owner_profile is None` alone can't carry this
    signal: test stub graphs already use a bare `StageSpec(stage_id=...)`
    (`owner_profile` defaulting to `None`) as a *generic, still
    executor-backed* stand-in stage, so branching on `owner_profile` would
    silently change their meaning too.
    """

    stage_id: StageId
    owner_profile: str | None = None
    depends_on: tuple[StageId, ...] = ()
    allowed_write_paths: tuple[str, ...] = ()
    commit_strategy: CommitStrategy = CommitStrategy.NONE
    checkpoint_after: ApprovalCheckpointKind | None = None
    requires_agent: bool = True


class GateOutcome(BaseModel):
    """Result of one gate check at a stage boundary."""

    gate_name: str
    passed: bool
    details: str = ""


class StageResult(BaseModel):
    """Per-stage entry in graph.json."""

    stage_id: StageId
    status: StageStatus = StageStatus.PENDING
    attempts: int = 0
    started_at: datetime | None = None
    finished_at: datetime | None = None
    commits: tuple[str, ...] = ()
    gate_results: tuple[GateOutcome, ...] = ()


class GraphState(BaseModel):
    """graph.json: per-stage status for one run, plus its checkpoint/terminal state.

    `scenario_id` is persisted here (not just passed around in memory) so
    approve/reject/answer/stop — invoked with just a run_id — can recover it to
    re-enter drive() without the caller having to re-supply it.
    """

    run_id: str
    scenario_id: str
    stages: dict[StageId, StageResult] = Field(default_factory=dict)
    pending_checkpoint: ApprovalCheckpointKind | None = None
    terminal_state: RunState | None = None
    base_commit: str | None = None
    started_at: datetime | None = None
    last_checkpoint_commit: str | None = None
    agent_call_count: int = 0
    inject_fault: bool = False
    fault_injected: bool = False
    clarification_answer: str | None = None
    target_repo_url: str | None = None
    base_ref: str | None = None
    requirement_text: str = ""
    req_id: str = ""
    template_path: str | None = None
