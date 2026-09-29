"""Hash-chained event log entry model (requirements.md C12, events.jsonl)."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class EventType(StrEnum):
    """Kinds of event recorded in the hash-chained log (C12-AC1)."""

    STAGE_STARTED = "stage_started"
    STAGE_FINISHED = "stage_finished"
    GATE_RESULT = "gate_result"
    POLICY_RESULT = "policy_result"
    APPROVAL_REQUESTED = "approval_requested"
    APPROVAL_RECORDED = "approval_recorded"
    RETRY = "retry"
    ROLLBACK = "rollback"
    STOP = "stop"
    FAULT_INJECTED = "fault_injected"


class EventDraft(BaseModel):
    """Event content before it takes its place in the hash chain.

    `injected` is a first-class field (not buried in payload) so G-16's
    fault-injection events are trivially distinguishable from organic ones.
    Bundling these fields keeps `EventLog.append`/`_compute_hash` under the
    project's max-args limit.
    """

    run_id: str
    event_type: EventType
    recorded_at: datetime
    stage: str | None = None
    attempt: int | None = None
    agent_call_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    injected: bool = False


class Event(EventDraft):
    """One append-only, hash-chained entry in events.jsonl."""

    sequence: int
    prev_hash: str
    hash: str
