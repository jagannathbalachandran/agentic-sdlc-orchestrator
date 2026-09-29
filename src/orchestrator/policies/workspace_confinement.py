"""Workspace confinement policy (requirements.md C6): post-stage check that no
change lands outside the workspace.

A `git diff` inside the workspace's own repo can never itself produce a path
that escapes the repo root, but this checks the structural invariant directly
(no absolute path, no `..` traversal) as defense in depth — the orchestrator
must never trust an agent's write path without verifying it (CLAUDE.md).
Any hit is critical (C9's "critical violation" -> stopped): this is the
workspace boundary itself, not a scope-of-work concern.
"""

from __future__ import annotations

from pathlib import PurePosixPath

from orchestrator.policies.base import PolicyOutcome, PolicyResult, WorkspaceDiff

POLICY_ID = "workspace_confinement"
PARENT_TRAVERSAL_SEGMENT = ".."


def _escapes_workspace(path: str) -> bool:
    pure_path = PurePosixPath(path)
    return pure_path.is_absolute() or PARENT_TRAVERSAL_SEGMENT in pure_path.parts


class WorkspaceConfinementPolicy:
    """Flags any changed path that isn't confined to the workspace."""

    policy_id = POLICY_ID

    def check(self, diff: WorkspaceDiff) -> PolicyResult:
        violations = tuple(
            path for path in diff.changed_paths if _escapes_workspace(path)
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
