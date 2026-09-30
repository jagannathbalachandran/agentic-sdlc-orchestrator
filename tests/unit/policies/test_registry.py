"""Tests for orchestrator.policies.registry.build_default_policies (T6.2).

Run from the repo root (pytest's rootdir), matching cli/commands/_common.py's
existing convention that config/defaults.toml resolves relative to cwd.
"""

from __future__ import annotations

from fnmatch import fnmatch
from pathlib import Path

from orchestrator.policies.base import FileChange, WorkspaceDiff
from orchestrator.policies.registry import (
    _allowed_path_globs_union,
    build_default_policies,
)


def test_build_default_policies_returns_all_eight() -> None:
    policies = build_default_policies(approved_dependencies=("fastapi",))
    ids = {policy.policy_id for policy in policies}
    assert ids == {
        "workspace_confinement",
        "path_partitioning",
        "protected_paths",
        "main_protection",
        "secret_scan",
        "schema_change_control",
        "diff_size_limit",
        "dependency_control",
    }


def test_allowed_path_globs_union_covers_every_real_stage_output() -> None:
    globs = _allowed_path_globs_union()
    for path in (
        "00-source.md",
        "01-requirements.md",
        "02-design.md",
        "03-plan.md",
        "src/placeholder.py",
        "tests/unit/test_placeholder.py",
        "tests/acceptance/test_fr1.py",
        "README.md",
    ):
        assert any(fnmatch(path, glob) for glob in globs), path


def test_path_partitioning_from_the_registry_passes_a_real_run_shaped_diff() -> None:
    policies = build_default_policies()
    path_partitioning = next(p for p in policies if p.policy_id == "path_partitioning")
    diff = WorkspaceDiff(
        workspace_path=Path("/unused"),
        base_commit="base",
        head_commit="head",
        current_branch="run/demo",
        files=(
            FileChange(path="00-source.md", added_lines=(), removed_lines=()),
            FileChange(path="01-requirements.md", added_lines=(), removed_lines=()),
            FileChange(path="src/app.py", added_lines=(), removed_lines=()),
        ),
    )
    result = path_partitioning.check(diff)
    assert result.passed
