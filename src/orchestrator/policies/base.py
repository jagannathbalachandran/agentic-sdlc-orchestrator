"""Policy protocol and the workspace diff every policy checks against
(requirements.md C6).

Policies are evaluated once at S6, against the whole run's accumulated diff
(base_commit at run start -> HEAD) — not per-stage. `compute_diff` builds that
diff from real `git` output; a policy's own `check()` never shells out itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel

from orchestrator.workspace.git_ops import current_branch, run_git

ADDED_LINE_PREFIX = "+"
REMOVED_LINE_PREFIX = "-"
DIFF_HEADER_PREFIXES = ("+++", "---")


@dataclass(frozen=True)
class FileChange:
    """One changed file's path plus its added/removed content lines."""

    path: str
    added_lines: tuple[str, ...]
    removed_lines: tuple[str, ...]


@dataclass(frozen=True)
class WorkspaceDiff:
    """Everything a policy might need to inspect the run's accumulated change.

    Carries `workspace_path`/`base_commit`/`head_commit` (not just the changed
    lines) so a policy needing deeper inspection than a line diff — e.g.
    protected-paths' section-aware pyproject.toml check (G-4) — can read a
    file's full content at either commit via `git show`.
    """

    workspace_path: Path
    base_commit: str
    head_commit: str
    current_branch: str
    files: tuple[FileChange, ...]

    @property
    def changed_paths(self) -> tuple[str, ...]:
        return tuple(file.path for file in self.files)

    @property
    def total_changed_lines(self) -> int:
        return sum(
            len(file.added_lines) + len(file.removed_lines) for file in self.files
        )


class PolicyOutcome(StrEnum):
    """What a policy violation means for the run (requirements.md C6/C9)."""

    OK = "ok"
    CHANGE_CONTROL = "change_control"
    CRITICAL = "critical"


class PolicyResult(BaseModel):
    """One policy's verdict (C6-AC1/AC2: detection, outcome, evidence)."""

    policy_id: str
    passed: bool
    outcome: PolicyOutcome
    violations: tuple[str, ...] = ()


class Policy(Protocol):
    """One named, config-injected check against the run's accumulated diff."""

    policy_id: str

    def check(self, diff: WorkspaceDiff) -> PolicyResult:
        """Evaluate this policy against `diff`."""
        ...


def _parse_file_patch(patch: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    added = []
    removed = []
    for line in patch.splitlines():
        if line.startswith(DIFF_HEADER_PREFIXES):
            continue
        if line.startswith(ADDED_LINE_PREFIX):
            added.append(line[1:])
        elif line.startswith(REMOVED_LINE_PREFIX):
            removed.append(line[1:])
    return tuple(added), tuple(removed)


def compute_diff(workspace_path: Path, base_commit: str) -> WorkspaceDiff:
    """Build a `WorkspaceDiff` for everything committed since `base_commit`."""
    head_commit = run_git(workspace_path, "rev-parse", "HEAD")
    changed = run_git(workspace_path, "diff", "--name-only", base_commit, "HEAD")
    files = []
    for path in (line for line in changed.splitlines() if line.strip()):
        patch = run_git(workspace_path, "diff", base_commit, "HEAD", "--", path)
        added, removed = _parse_file_patch(patch)
        files.append(FileChange(path=path, added_lines=added, removed_lines=removed))
    return WorkspaceDiff(
        workspace_path=workspace_path,
        base_commit=base_commit,
        head_commit=head_commit,
        current_branch=current_branch(workspace_path),
        files=tuple(files),
    )
