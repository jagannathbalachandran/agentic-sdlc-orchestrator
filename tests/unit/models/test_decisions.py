"""Tests for orchestrator.models.decisions."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from orchestrator.models.decisions import Decision


def test_decision_accepts_minimal_valid_input() -> None:
    decision = Decision(
        decision_id="D-1",
        stage="S3",
        actor="architect",
        choice="Use TOML for config",
        rationale="Matches the NFR and avoids a new dependency.",
        recorded_at=datetime(2026, 9, 29, 12, 0, 0, tzinfo=UTC),
    )
    assert decision.depends_on == ()
    assert decision.artifact_hashes == ()


def test_decision_requires_rationale() -> None:
    with pytest.raises(ValidationError):
        Decision(
            decision_id="D-1",
            stage="S3",
            actor="architect",
            choice="x",
            recorded_at=datetime(2026, 9, 29, 12, 0, 0, tzinfo=UTC),
        )  # type: ignore[call-arg]
