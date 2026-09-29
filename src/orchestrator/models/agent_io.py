"""Agent call request/response models (architecture-proposal.md O-4, revised).

The response is a small execution summary only — deliverables are written by the
agent's own tools into the workspace and read from disk by gates, never parsed out
of this response (O-4).
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel


class AgentCallOutcome(StrEnum):
    """How one agent call ended."""

    SUCCESS = "success"
    TIMEOUT = "timeout"
    INVALID_OUTPUT = "invalid_output"
    ERROR = "error"


class AgentCallRequest(BaseModel):
    """What the executor needs to make one agent call."""

    profile_name: str
    stage: str
    task_id: str | None = None
    rendered_prompt: str
    workspace_path: str
    timeout_seconds: int
    budget_usd: float


class AgentCallResponse(BaseModel):
    """Executor call result: a small summary, not stage-output content (O-4)."""

    outcome: AgentCallOutcome
    summary: str = ""
    produced_ids: tuple[str, ...] = ()
    files_written: tuple[str, ...] = ()
    duration_seconds: float
    cost_usd: float | None = None
    session_id: str | None = None
