"""Tests for orchestrator.audit.approvals_log."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from orchestrator.audit.approvals_log import append_approval, read_approvals
from orchestrator.models.approvals import (
    ApprovalCheckpointKind,
    ApprovalDecision,
    ApprovalRecord,
)


def _record(comment: str) -> ApprovalRecord:
    return ApprovalRecord(
        checkpoint=ApprovalCheckpointKind.DESIGN,
        artifact_hashes=("abc123",),
        decision=ApprovalDecision.APPROVE,
        comment=comment,
        approver="alice",
        decided_at=datetime(2026, 9, 29, 12, 0, 0, tzinfo=UTC),
    )


def test_read_approvals_returns_empty_list_for_a_missing_file(tmp_path: Path) -> None:
    assert read_approvals(tmp_path / "approvals.jsonl") == []


def test_append_then_read_round_trips_in_order(tmp_path: Path) -> None:
    path = tmp_path / "approvals.jsonl"
    append_approval(path, _record("first"))
    append_approval(path, _record("second"))

    records = read_approvals(path)
    assert [record.comment for record in records] == ["first", "second"]
