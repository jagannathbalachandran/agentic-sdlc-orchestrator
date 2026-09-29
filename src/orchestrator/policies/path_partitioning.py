"""Path partitioning policy (requirements.md C6, §7.3): each stage writes only
its allowed paths.

Evaluated once at S6 over the whole run's diff, against the *union* of every
stage's `StageSpec.allowed_write_paths` — S6 doesn't know which stage wrote
which file (two sibling stages can even share one commit, T6.1), so it checks
"was every changed file allowed for *some* stage", not per-stage attribution.
A hit means an agent wrote somewhere no stage was ever meant to touch — the
same class of containment concern as workspace confinement, so also critical.
"""

from __future__ import annotations

from fnmatch import fnmatch

from orchestrator.policies.base import PolicyOutcome, PolicyResult, WorkspaceDiff

POLICY_ID = "path_partitioning"


class PathPartitioningPolicy:
    """Flags any changed path outside the configured allowed-path globs."""

    policy_id = POLICY_ID

    def __init__(self, allowed_path_globs: tuple[str, ...]) -> None:
        self._allowed_path_globs = allowed_path_globs

    def check(self, diff: WorkspaceDiff) -> PolicyResult:
        if not self._allowed_path_globs:
            return PolicyResult(
                policy_id=self.policy_id, passed=True, outcome=PolicyOutcome.OK
            )
        violations = tuple(
            path
            for path in diff.changed_paths
            if not any(fnmatch(path, glob) for glob in self._allowed_path_globs)
        )
        if not violations:
            return PolicyResult(
                policy_id=self.policy_id, passed=True, outcome=PolicyOutcome.OK
            )
        return PolicyResult(
            policy_id=self.policy_id,
            passed=False,
            outcome=PolicyOutcome.CRITICAL,
            violations=violations,
        )
