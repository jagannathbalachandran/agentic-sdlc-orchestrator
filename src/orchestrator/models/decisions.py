"""Decision lineage model (requirements.md C10-AC6, decisions.jsonl)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class Decision(BaseModel):
    """One recorded decision: id, stage, actor, choice, rationale, dependencies."""

    decision_id: str
    stage: str
    actor: str
    choice: str
    rationale: str
    recorded_at: datetime
    depends_on: tuple[str, ...] = ()
    artifact_hashes: tuple[str, ...] = ()
