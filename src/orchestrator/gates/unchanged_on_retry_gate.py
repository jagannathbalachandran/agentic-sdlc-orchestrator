"""Exit gate: on a retry (attempt > 1), a stage's own deliverable file must
have actually changed since the workspace's last commit — an agent call that
reports success but leaves the file byte-for-byte identical to before almost
certainly didn't do the work (replied with prose, misread the prompt, or
otherwise never revised anything).

Found on a real run (item 4/T9.7): a Design rejection's re-run passed every
other gate, but 02-design.md was byte-for-byte the original — the failure
was silent until this gate existed. Compares against the commit at HEAD when
this attempt's exit gates run, since the current attempt's own commit
(`engine/runner.py`'s `stage_commit_hook`) only happens *after* exit gates
pass — HEAD at gate-check time is still whatever the previous attempt left.
"""

from __future__ import annotations

from dataclasses import dataclass

from orchestrator.gates.base import StageContext
from orchestrator.models.graph import GateOutcome
from orchestrator.workspace.git_ops import (
    current_commit_or_empty_tree,
    read_file_at_commit,
)


@dataclass(frozen=True)
class UnchangedOnRetryGate:
    """Fails if `relative_path` is byte-for-byte identical to its content at
    the last commit, on any attempt after the first."""

    gate_name: str = "changed_on_retry"
    relative_path: str = "02-design.md"

    def check(self, context: StageContext) -> GateOutcome:
        if context.attempt <= 1:
            return GateOutcome(
                gate_name=self.gate_name,
                passed=True,
                details="first attempt; nothing to compare against",
            )
        path = context.workspace_path / self.relative_path
        if not path.is_file():
            return GateOutcome(
                gate_name=self.gate_name,
                passed=True,
                details=f"{self.relative_path} not found; a different gate covers that",
            )
        current_content = path.read_text(encoding="utf-8")
        head_commit = current_commit_or_empty_tree(context.workspace_path)
        previous_content = read_file_at_commit(
            context.workspace_path, head_commit, self.relative_path
        )
        if current_content == previous_content:
            return GateOutcome(
                gate_name=self.gate_name,
                passed=False,
                details=(
                    f"{self.relative_path} is unchanged since the last commit on "
                    f"retry attempt {context.attempt} — the agent call didn't "
                    "actually revise it"
                ),
            )
        return GateOutcome(
            gate_name=self.gate_name,
            passed=True,
            details=f"{self.relative_path} changed since the last commit",
        )
