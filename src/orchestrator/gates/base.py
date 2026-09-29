"""Gate protocol and the context every gate (and, later, policy) checks against."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from orchestrator.models.graph import GateOutcome, StageId


@dataclass(frozen=True)
class StageContext:
    """What a gate needs to inspect at a stage boundary."""

    run_id: str
    stage_id: StageId
    attempt: int
    workspace_path: Path


class Gate(Protocol):
    """One named check; StageRunner records its GateOutcome as an event."""

    def check(self, context: StageContext) -> GateOutcome:
        """Evaluate this gate against the current stage boundary."""
        ...
