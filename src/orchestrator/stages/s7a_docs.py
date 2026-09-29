"""S7a Docs — StageSpec binding (requirements.md §7).

Chained after S6 for now; T6.1's scheduler restores the real parallel-join shape
with S7b (both depending on S6 directly).
"""

from __future__ import annotations

from orchestrator.models.graph import CommitStrategy, StageId, StageSpec

SPEC = StageSpec(
    stage_id=StageId.S7A_DOCS,
    owner_profile="technical_writer",
    depends_on=(StageId.S6_VERIFY,),
    commit_strategy=CommitStrategy.ONE,
)
