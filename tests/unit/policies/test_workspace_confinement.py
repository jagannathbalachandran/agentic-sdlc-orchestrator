"""Tests for orchestrator.policies.workspace_confinement (C6-AC1)."""

from __future__ import annotations

from pathlib import Path

from orchestrator.policies.base import FileChange, WorkspaceDiff
from orchestrator.policies.workspace_confinement import WorkspaceConfinementPolicy


def _diff(paths: tuple[str, ...]) -> WorkspaceDiff:
    return WorkspaceDiff(
        workspace_path=Path("/workspace"),
        base_commit="base",
        head_commit="head",
        current_branch="run/demo",
        files=tuple(
            FileChange(path=path, added_lines=(), removed_lines=()) for path in paths
        ),
    )


def test_passes_when_every_changed_path_stays_inside_the_workspace() -> None:
    result = WorkspaceConfinementPolicy().check(
        _diff(("src/app.py", "tests/unit/test_app.py"))
    )
    assert result.passed
    assert result.outcome.value == "ok"


def test_flags_an_absolute_path_as_critical() -> None:
    result = WorkspaceConfinementPolicy().check(_diff(("/etc/passwd",)))
    assert not result.passed
    assert result.outcome.value == "critical"
    assert "/etc/passwd" in result.violations


def test_flags_a_parent_traversal_path_as_critical() -> None:
    result = WorkspaceConfinementPolicy().check(_diff(("../outside/file.py",)))
    assert not result.passed
    assert result.outcome.value == "critical"
    assert result.violations == ("../outside/file.py",)
