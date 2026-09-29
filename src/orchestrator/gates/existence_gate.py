"""Stub existence gate: S2's exit gate (every referenced file/symbol exists).

Real checking needs S2's actual analysis output (T4's real executor) — stubbed
here since the mock executor's generic fixture has nothing concrete to check
against yet.
"""

from __future__ import annotations

from orchestrator.gates.base import StageContext
from orchestrator.models.graph import GateOutcome

GATE_NAME = "existence"


class ExistenceGate:
    """Stub: always passes."""

    def check(self, context: StageContext) -> GateOutcome:
        """Always pass; a structural placeholder for S2's real existence check."""
        del context
        return GateOutcome(
            gate_name=GATE_NAME,
            passed=True,
            details="stub: existence check not yet implemented",
        )
