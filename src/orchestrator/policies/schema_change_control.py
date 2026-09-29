"""Schema change control policy (requirements.md C6): new/changed migrations
require Change-control approval, not an automatic pass.
"""

from __future__ import annotations

from fnmatch import fnmatch

from orchestrator.policies.base import PolicyOutcome, PolicyResult, WorkspaceDiff

POLICY_ID = "schema_change_control"


class SchemaChangeControlPolicy:
    """Flags any changed path that looks like a database migration."""

    policy_id = POLICY_ID

    def __init__(self, migration_path_globs: tuple[str, ...]) -> None:
        self._migration_path_globs = migration_path_globs

    def check(self, diff: WorkspaceDiff) -> PolicyResult:
        violations = tuple(
            path
            for path in diff.changed_paths
            if any(fnmatch(path, glob) for glob in self._migration_path_globs)
        )
        if not violations:
            return PolicyResult(
                policy_id=self.policy_id, passed=True, outcome=PolicyOutcome.OK
            )
        return PolicyResult(
            policy_id=self.policy_id,
            passed=False,
            outcome=PolicyOutcome.CHANGE_CONTROL,
            violations=violations,
        )
