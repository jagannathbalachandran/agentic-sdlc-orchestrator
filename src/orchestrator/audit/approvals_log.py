"""Append-only approvals.jsonl: one line per resolved checkpoint (C7-AC3)."""

from __future__ import annotations

from pathlib import Path

from orchestrator.models.approvals import ApprovalRecord


def append_approval(path: Path, record: ApprovalRecord) -> None:
    """Append one resolved-checkpoint record."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(record.model_dump_json() + "\n")


def read_approvals(path: Path) -> list[ApprovalRecord]:
    """Read every resolved-checkpoint record, in order."""
    if not path.is_file():
        return []
    return [
        ApprovalRecord.model_validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
