"""Tests for orchestrator.policies.protected_paths (C6-AC1, architecture-proposal.md
G-4/G-5).
"""

from __future__ import annotations

from pathlib import Path

from orchestrator.policies.base import FileChange, WorkspaceDiff, compute_diff
from orchestrator.policies.protected_paths import ProtectedPathsPolicy
from orchestrator.workspace.git_ops import commit_all, init_repo

PROTECTED_GLOBS = (
    ".github/**",
    "scripts/check.py",
    ".orchestrator/**",
    "docs/requirements/*/00-source.md",
    ".env*",
    "*.pem",
    "id_rsa*",
    "*.key",
)


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


def test_passes_when_nothing_protected_changed() -> None:
    result = ProtectedPathsPolicy(PROTECTED_GLOBS).check(_diff(("src/app.py",)))
    assert result.passed
    assert result.outcome.value == "ok"


def test_flags_a_whole_file_protected_path_as_critical() -> None:
    result = ProtectedPathsPolicy(PROTECTED_GLOBS).check(
        _diff((".github/workflows/ci.yml",))
    )
    assert not result.passed
    assert result.outcome.value == "critical"
    assert ".github/workflows/ci.yml" in result.violations


def test_flags_scripts_check_py_as_critical() -> None:
    result = ProtectedPathsPolicy(PROTECTED_GLOBS).check(_diff(("scripts/check.py",)))
    assert not result.passed
    assert result.outcome.value == "critical"


def test_env_example_is_exempt_despite_matching_the_env_glob() -> None:
    result = ProtectedPathsPolicy(PROTECTED_GLOBS).check(_diff((".env.example",)))
    assert result.passed


def test_a_prior_reqs_00_source_md_baseline_is_protected_not_only_the_current_run() -> (
    None
):
    result = ProtectedPathsPolicy(PROTECTED_GLOBS).check(
        _diff(("docs/requirements/REQ-1/00-source.md",))
    )
    assert not result.passed
    assert result.outcome.value == "critical"


PYPROJECT_BASE = """\
[project]
name = "shortener"

[project.dependencies]
fastapi = ">=0.115.0"

[tool.ruff]
target-version = "py311"

[tool.mypy]
strict = true
"""


def test_flags_a_protected_toml_table_edit_as_critical(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    init_repo(workspace)
    (workspace / "pyproject.toml").write_text(PYPROJECT_BASE, encoding="utf-8")
    base_commit = commit_all(workspace, "base")

    edited = PYPROJECT_BASE.replace(
        'target-version = "py311"', 'target-version = "py312"'
    )
    (workspace / "pyproject.toml").write_text(edited, encoding="utf-8")
    commit_all(workspace, "edit ruff config")

    diff = compute_diff(workspace, base_commit)
    result = ProtectedPathsPolicy(PROTECTED_GLOBS).check(diff)

    assert not result.passed
    assert result.outcome.value == "critical"
    assert any("pyproject.toml" in violation for violation in result.violations)


def test_does_not_flag_editing_project_dependencies_alone(tmp_path: Path) -> None:
    """G-4: dependency control needs to add an approved dependency to
    [project.dependencies] without protected-paths blocking it — only the
    quality-config tables are protected, not the whole file.
    """
    workspace = tmp_path / "workspace"
    init_repo(workspace)
    (workspace / "pyproject.toml").write_text(PYPROJECT_BASE, encoding="utf-8")
    base_commit = commit_all(workspace, "base")

    edited = PYPROJECT_BASE.replace(
        'fastapi = ">=0.115.0"',
        'fastapi = ">=0.115.0"\nhttpx = ">=0.27.0"',
    )
    (workspace / "pyproject.toml").write_text(edited, encoding="utf-8")
    commit_all(workspace, "add an approved dependency")

    diff = compute_diff(workspace, base_commit)
    result = ProtectedPathsPolicy(PROTECTED_GLOBS).check(diff)

    assert result.passed
