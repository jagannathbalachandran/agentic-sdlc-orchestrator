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
    """Declarative descriptor for one stage in the fixed Phase 1 graph."""

    stage_id: StageId
    owner_profile: str | None = None
    depends_on: tuple[StageId, ...] = ()
    allowed_write_paths: tuple[str, ...] = ()
    commit_strategy: CommitStrategy = CommitStrategy.NONE
    checkpoint_after: ApprovalCheckpointKind | None = None


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
