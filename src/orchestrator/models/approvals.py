"""Approval checkpoint models (requirements.md C7, approvals.jsonl)."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel


class ApprovalCheckpointKind(StrEnum):
    """The four checkpoint kinds (requirements.md C7)."""

    CLARIFICATION = "clarification"
    DESIGN = "design"
    CHANGE_CONTROL = "change_control"
    RELEASE = "release"


class ApprovalDecision(StrEnum):
    """What a human did at a checkpoint."""

    APPROVE = "approve"
    REJECT = "reject"
    REJECT_FINAL = "reject_final"
    ANSWER = "answer"


class ApprovalRecord(BaseModel):
    """One resolved approval checkpoint (requirements.md C7-AC3)."""

    checkpoint: ApprovalCheckpointKind
    artifact_hashes: tuple[str, ...]
    decision: ApprovalDecision
    comment: str
    approver: str
    decided_at: datetime
