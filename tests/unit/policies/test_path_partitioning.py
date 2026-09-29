"""Tests for orchestrator.policies.path_partitioning (C6-AC1, §7.3)."""

from __future__ import annotations

from pathlib import Path

from orchestrator.policies.base import FileChange, WorkspaceDiff
from orchestrator.policies.path_partitioning import PathPartitioningPolicy


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


def test_passes_when_every_changed_path_matches_an_allowed_glob() -> None:
    policy = PathPartitioningPolicy(("src/**", "tests/unit/**"))
    result = policy.check(_diff(("src/app.py", "tests/unit/test_app.py")))
    assert result.passed
    assert result.outcome.value == "ok"


def test_flags_a_changed_path_outside_every_allowed_glob_as_critical() -> None:
    policy = PathPartitioningPolicy(("src/**",))
    result = policy.check(_diff(("src/app.py", "scripts/rogue.py")))
    assert not result.passed
    assert result.outcome.value == "critical"
    assert result.violations == ("scripts/rogue.py",)


def test_no_configured_globs_means_unrestricted() -> None:
    policy = PathPartitioningPolicy(())
    result = policy.check(_diff(("anything/at/all.py",)))
    assert result.passed
