"""S2 Codebase analysis — StageSpec binding (requirements.md §7).

Always runs for now — "skipped for greenfield" (C4-AC3) needs project-type
detection that isn't wired into the graph yet; deferred, documented in
docs/build-notes.md.
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
