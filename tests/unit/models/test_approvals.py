"""Tests for orchestrator.models.approvals."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from orchestrator.models.approvals import (
    ApprovalCheckpointKind,
    ApprovalDecision,
    ApprovalRecord,
)


def test_approval_record_accepts_minimal_valid_input() -> None:
    record = ApprovalRecord(
        checkpoint=ApprovalCheckpointKind.DESIGN,
        artifact_hashes=("abc123",),
        decision=ApprovalDecision.APPROVE,
        comment="Looks good.",
        approver="jagannath",
        decided_at=datetime(2026, 9, 29, 12, 0, 0, tzinfo=UTC),
    )
    assert record.decision is ApprovalDecision.APPROVE


def test_approval_record_rejects_unknown_checkpoint_kind() -> None:
    with pytest.raises(ValidationError):
        ApprovalRecord(
            checkpoint="not-a-real-checkpoint",  # type: ignore[arg-type]
            artifact_hashes=(),
            decision=ApprovalDecision.APPROVE,
            comment="",
            approver="jagannath",
            decided_at=datetime(2026, 9, 29, 12, 0, 0, tzinfo=UTC),
        )
