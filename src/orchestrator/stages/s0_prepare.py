"""S0 Prepare — StageSpec binding (requirements.md §7).

Owner "Orchestrator" (not an agent role): workspace/run-branch setup and
writing `00-source.md` are done by the orchestrator itself (engine/fsm.py's
S0 commit hook) — `requires_agent=False` so this never reaches the executor.
"""

from __future__ import annotations

from orchestrator.models.graph import CommitStrategy, StageId, StageSpec

SPEC = StageSpec(
    stage_id=StageId.S0_PREPARE,
    owner_profile=None,
    depends_on=(),
    allowed_write_paths=("00-source.md",),
    commit_strategy=CommitStrategy.ONE,
    requires_agent=False,
)
