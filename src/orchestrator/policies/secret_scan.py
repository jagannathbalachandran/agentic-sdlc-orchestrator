"""Secret scan policy (requirements.md C6, architecture-proposal.md G-7):
pattern scan of every stage diff. A hit is critical -> stopped.

In-house regex set (`config/defaults.toml`'s `policy.secret_scan_patterns`),
not a dedicated scanner dependency — G-7's explicit, documented trade-off: a
narrower net than `detect-secrets`/`gitleaks`, in exchange for zero new
dependencies.
"""

from __future__ import annotations

import re

from orchestrator.policies.base import PolicyOutcome, PolicyResult, WorkspaceDiff

POLICY_ID = "secret_scan"


class SecretScanPolicy:
    """Flags any added line matching a configured secret pattern."""

    policy_id = POLICY_ID

    def __init__(self, patterns: tuple[str, ...]) -> None:
        self._patterns = tuple(re.compile(pattern) for pattern in patterns)

    def check(self, diff: WorkspaceDiff) -> PolicyResult:
        violations = tuple(
            f"{file.path}: matched a secret-like pattern"
            for file in diff.files
            for line in file.added_lines
            if any(pattern.search(line) for pattern in self._patterns)
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
