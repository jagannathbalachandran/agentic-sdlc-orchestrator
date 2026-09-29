"""Approval gate: fails if the run has an unresolved pending checkpoint.

Not wired as a StageRunner entry gate — engine.fsm.drive()'s own
pending_checkpoint check already blocks any stage from running while paused,
earlier and more directly than a per-stage gate could (drive() returns before
even looking for the next pending stage). Kept as a standalone, independently
testable component matching the architecture's module list; available if a
future caller ever needs this check outside fsm.drive()'s own control flow.
"""

from __future__ import annotations

from dataclasses import dataclass

from orchestrator.gates.base import StageContext
from orchestrator.models.graph import GateOutcome, GraphState

GATE_NAME = "approval"


@dataclass(frozen=True)
class ApprovalGate:
    """Fails while `graph_state` has an unresolved pending checkpoint."""

    graph_state: GraphState

    def check(self, context: StageContext) -> GateOutcome:
        """Fail if a checkpoint is pending; pass otherwise."""
        del context
        if self.graph_state.pending_checkpoint is not None:
            return GateOutcome(
                gate_name=GATE_NAME,
                passed=False,
                details=f"awaiting approval: {self.graph_state.pending_checkpoint.value}",
            )
        return GateOutcome(gate_name=GATE_NAME, passed=True)
