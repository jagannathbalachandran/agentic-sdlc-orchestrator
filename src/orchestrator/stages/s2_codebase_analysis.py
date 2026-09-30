"""S2 Codebase analysis — StageSpec binding (requirements.md §7).

Skipped for greenfield, runs otherwise (C4-AC3) — decided dynamically at
drive-time from `graph_state.base_ref is None`, not a static property of
this spec (`engine/fsm.py:_build_runner`/`_SkippedS2Runner`).
"""

from __future__ import annotations

from orchestrator.models.graph import CommitStrategy, StageId, StageSpec

SPEC = StageSpec(
    stage_id=StageId.S2_CODEBASE_ANALYSIS,
    owner_profile="analyst",
    depends_on=(StageId.S1_REQUIREMENTS,),
    allowed_write_paths=("02-impact-analysis.md",),
    commit_strategy=CommitStrategy.NONE,
)
