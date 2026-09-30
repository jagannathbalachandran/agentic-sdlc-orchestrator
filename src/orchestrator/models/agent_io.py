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
    """What the executor needs to make one agent call.

    `scenario_id` and `attempt` key mock-fixture lookup (O-8, `(scenario_id,
    stage_id, attempt)`) and are equally useful for the real executor's own
    logging/correlation, so they live on the shared request rather than being
    mock-only parameters.
    """

    profile_name: str
    scenario_id: str
    stage: str
    attempt: int = 1
    task_id: str | None = None
    rendered_prompt: str
    workspace_path: str
    timeout_seconds: int
    budget_usd: float


class AgentCallResponse(BaseModel):
    """Executor call result: a small summary, not stage-output content (O-4).

    `high_severity_findings` is S7b-specific (empty for every other stage) —
    the reviewer profile's own finding IDs it judged high severity, driving
    the S7b-findings bounded retry (T7.1, G-15) without needing to parse the
    findings report file itself. `blocking_questions` is S1-specific in the
    same way — the analyst profile's own questions it couldn't resolve from
    the REQ text alone, driving the Clarification checkpoint (T7.4, C7).
    """

    outcome: AgentCallOutcome
    summary: str = ""
    produced_ids: tuple[str, ...] = ()
    files_written: tuple[str, ...] = ()
    high_severity_findings: tuple[str, ...] = ()
    blocking_questions: tuple[str, ...] = ()
    duration_seconds: float
    cost_usd: float | None = None
    session_id: str | None = None


class AgentCallTranscript(BaseModel):
    """One agent call's full record (C8-AC4: "every call records role,
    profile version, prompt, response, duration, outcome"; §11's `agents/`
    directory) — written once per call, regardless of executor kind, so a
    real and a mock run leave the same kind of record on disk.
    """

    agent_call_id: str
    run_id: str
    stage: str
    attempt: int
    task_id: str | None = None
    role: str
    profile_version_hash: str | None = None
    prompt: str
    response: AgentCallResponse
