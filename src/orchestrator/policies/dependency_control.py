"""Dependency control policy (requirements.md C6): new deps only from the
project's approved list; else Change-control approval.

Scans added lines in `pyproject.toml`'s `[project.dependencies]`/
`[project.optional-dependencies]` tables (the only place `templates/
python-service/pyproject.toml` and both registered target repos declare
dependencies) for a package name not already on the project's
`approved_dependencies` list (`.orchestrator/project.toml`, T5.2).
"""

from __future__ import annotations

import re

from orchestrator.policies.base import PolicyOutcome, PolicyResult, WorkspaceDiff

POLICY_ID = "dependency_control"
DEFAULT_WATCHED_PATHS = ("pyproject.toml",)

# A dependency-list entry line, e.g. `    "fastapi>=0.115.0",` — captures the
# package name up to the first version/extra/marker specifier.
_DEPENDENCY_LINE = re.compile(r'^\s*"([A-Za-z0-9][A-Za-z0-9._-]*)')


def _normalize(name: str) -> str:
    return name.lower().replace("_", "-")


class DependencyControlPolicy:
    """Flags any newly added dependency not on the project's approved list."""

    policy_id = POLICY_ID

    def __init__(
        self,
        approved_dependencies: tuple[str, ...],
        watched_paths: tuple[str, ...] = DEFAULT_WATCHED_PATHS,
    ) -> None:
        self._approved = {_normalize(name) for name in approved_dependencies}
        self._watched_paths = watched_paths

    def check(self, diff: WorkspaceDiff) -> PolicyResult:
        violations = tuple(
            f"{file.path}: new dependency '{match.group(1)}'"
            for file in diff.files
            if file.path in self._watched_paths
            for line in file.added_lines
            for match in (_DEPENDENCY_LINE.match(line),)
            if match is not None and _normalize(match.group(1)) not in self._approved
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
