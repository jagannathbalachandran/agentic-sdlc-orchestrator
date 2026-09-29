"""Main protection policy (requirements.md C6): no commit/push to `main`.

Every run works on its own `run/<run-id>` branch (D-5, workspace/manager.py's
create_branch, called before any agent executes) — being on `main` at S6 means
that branching was somehow bypassed. An attempt is critical -> stopped (C6).
"""

from __future__ import annotations

from orchestrator.policies.base import PolicyOutcome, PolicyResult, WorkspaceDiff

POLICY_ID = "main_protection"
PROTECTED_BRANCH_NAME = "main"


class MainProtectionPolicy:
    """Flags the run being on the protected branch at all."""

    policy_id = POLICY_ID

    def check(self, diff: WorkspaceDiff) -> PolicyResult:
        if diff.current_branch != PROTECTED_BRANCH_NAME:
            return PolicyResult(
                policy_id=self.policy_id, passed=True, outcome=PolicyOutcome.OK
            )
        return PolicyResult(
            policy_id=self.policy_id,
            passed=False,
            outcome=PolicyOutcome.CRITICAL,
            violations=(f"run is on protected branch '{PROTECTED_BRANCH_NAME}'",),
        )
