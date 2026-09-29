"""Run-level domain models: the shape of run.json (requirements.md §11)."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from orchestrator.models._patterns import REQ_ID_PATTERN, RUN_ID_PATTERN


class RunState(StrEnum):
    """Run lifecycle states (requirements.md §6.2)."""

    CREATED = "created"
    PREPARING = "preparing"
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    REJECTED = "rejected"
    STOPPED = "stopped"


TERMINAL_RUN_STATES = frozenset(
    {RunState.COMPLETED, RunState.FAILED, RunState.REJECTED, RunState.STOPPED}
)


class ExecutorKind(StrEnum):
    """Which executor backs the agent calls for a run."""

    REAL = "real"
    MOCK = "mock"


class RunRecord(BaseModel):
    """Orchestrator-owned run record (requirements.md §11, run.json)."""

    run_id: str = Field(pattern=RUN_ID_PATTERN)
    project: str
    scenario_id: str
    req_id: str = Field(pattern=REQ_ID_PATTERN)
    operator: str
    state: RunState
    outcome_reason: str | None = None
    started_at: datetime
    completed_at: datetime | None = None
    target_url: str
    config_commit: str
    base_ref: str | None = None
    base_commit: str
    run_branch: str
    push_result: str | None = None
    orchestrator_version: str
    template_version: str | None = None
    profile_versions: dict[str, str] = Field(default_factory=dict)
    executor_kind: ExecutorKind
    model: str | None = None
    effective_config_hash: str
