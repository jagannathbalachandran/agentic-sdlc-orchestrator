"""Tests for orchestrator.policies.diff_size_limit (C6-AC1, architecture-proposal.md G-6)."""

from __future__ import annotations

from pathlib import Path

from orchestrator.policies.base import FileChange, WorkspaceDiff
from orchestrator.policies.diff_size_limit import DiffSizeLimitPolicy


def _diff(files: tuple[FileChange, ...]) -> WorkspaceDiff:
    return WorkspaceDiff(
        workspace_path=Path("/workspace"),
        base_commit="base",
        head_commit="head",
        current_branch="run/demo",
        files=files,
    )


def test_passes_when_under_both_limits() -> None:
    diff = _diff(
        (FileChange(path="src/app.py", added_lines=("a", "b"), removed_lines=()),)
    )
    result = DiffSizeLimitPolicy(max_lines=10, max_files=5).check(diff)
    assert result.passed
    assert result.outcome.value == "ok"


def test_flags_exceeding_the_line_limit_as_change_control() -> None:
    diff = _diff(
        (
            FileChange(
                path="src/app.py",
                added_lines=tuple("x" for _ in range(5)),
                removed_lines=(),
            ),
        )
    )
    result = DiffSizeLimitPolicy(max_lines=3, max_files=5).check(diff)
    assert not result.passed
    assert result.outcome.value == "change_control"
    assert any("changed lines" in violation for violation in result.violations)


def test_flags_exceeding_the_file_limit_as_change_control() -> None:
    diff = _diff(
        (
            FileChange(path="a.py", added_lines=(), removed_lines=()),
            FileChange(path="b.py", added_lines=(), removed_lines=()),
            FileChange(path="c.py", added_lines=(), removed_lines=()),
        )
    )
    result = DiffSizeLimitPolicy(max_lines=1000, max_files=2).check(diff)
    assert not result.passed
    assert result.outcome.value == "change_control"
    assert any("changed files" in violation for violation in result.violations)
