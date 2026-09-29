"""Stub schema gate: always passes.

Real per-stage output-schema validation needs real agent output (T4) and isn't
meaningful to check against the mock executor's generic fixtures — this is a
structural placeholder so every stage has an entry/exit gate and every gate
result is recorded as an event (C5-AC3), ahead of real validation landing later.
"""

from __future__ import annotations

from orchestrator.gates.base import StageContext
from orchestrator.models.graph import GateOutcome

GATE_NAME = "schema"


class SchemaGate:
    """Stub: always passes."""

    def check(self, context: StageContext) -> GateOutcome:
        """Always pass; a structural placeholder, not real validation yet."""
        del context
        return GateOutcome(
            gate_name=GATE_NAME,
            passed=True,
            details="stub: schema validation not yet implemented",
        )
