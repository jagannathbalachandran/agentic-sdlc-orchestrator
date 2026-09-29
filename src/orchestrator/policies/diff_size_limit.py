"""Diff size limit policy (requirements.md C6): above threshold requires
Change-control approval instead of an automatic pass.

Defaults (`config/defaults.toml`'s `limits.diff_size_limit_lines`/
`diff_size_limit_files`) per architecture-proposal.md G-6.
"""

from __future__ import annotations

from orchestrator.policies.base import PolicyOutcome, PolicyResult, WorkspaceDiff

POLICY_ID = "diff_size_limit"


class DiffSizeLimitPolicy:
    """Flags a run diff that exceeds the configured line or file count limit."""

    policy_id = POLICY_ID

    def __init__(self, max_lines: int, max_files: int) -> None:
        self._max_lines = max_lines
        self._max_files = max_files

    def check(self, diff: WorkspaceDiff) -> PolicyResult:
        violations = []
        if diff.total_changed_lines > self._max_lines:
            violations.append(
                f"{diff.total_changed_lines} changed lines exceeds limit "
                f"{self._max_lines}"
            )
        if len(diff.files) > self._max_files:
            violations.append(
                f"{len(diff.files)} changed files exceeds limit {self._max_files}"
            )
        if not violations:
            return PolicyResult(
                policy_id=self.policy_id, passed=True, outcome=PolicyOutcome.OK
            )
        return PolicyResult(
            policy_id=self.policy_id,
            passed=False,
            outcome=PolicyOutcome.CHANGE_CONTROL,
            violations=tuple(violations),
        )
