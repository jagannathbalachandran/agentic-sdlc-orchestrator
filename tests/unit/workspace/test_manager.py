"""Tests for orchestrator.workspace.manager."""

from __future__ import annotations

from pathlib import Path

from orchestrator.workspace.git_ops import commit_all, init_repo, run_git
from orchestrator.workspace.manager import (
    create_run_branch,
    init_existing_workspace,
    init_greenfield_workspace,
)


def test_init_greenfield_workspace_copies_template_and_records_null_base_ref(
    tmp_path: Path,
) -> None:
    template = tmp_path / "template"
    template.mkdir()
    (template / "pyproject.toml").write_text(
        '[project]\nname = "demo"\n', encoding="utf-8"
    )

    workspace = tmp_path / "workspace"
    result = init_greenfield_workspace(workspace, template)

    assert result.base_ref is None
    assert len(result.base_commit) == 40
    assert (workspace / "pyproject.toml").is_file()
    assert (workspace / ".git").is_dir()


def test_init_existing_workspace_clones_at_base_ref_and_records_its_commit(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    init_repo(source)
    (source / "README.md").write_text("v1\n", encoding="utf-8")
    baseline_sha = commit_all(source, "v1")
    run_git(source, "tag", "baseline-greenfield")
    (source / "README.md").write_text("v2\n", encoding="utf-8")
    commit_all(source, "v2")

    workspace = tmp_path / "workspace"
    result = init_existing_workspace(workspace, source, "baseline-greenfield")

    assert result.base_ref == "baseline-greenfield"
    assert result.base_commit == baseline_sha
    assert (workspace / "README.md").read_text(encoding="utf-8") == "v1\n"


def test_create_run_branch_creates_run_slash_prefixed_branch(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    init_repo(workspace)
    (workspace / "f.txt").write_text("x", encoding="utf-8")
    commit_all(workspace, "init")

    branch_name = create_run_branch(workspace, "demo-20260929-001")

    assert branch_name == "run/demo-20260929-001"
    assert run_git(workspace, "branch", "--show-current") == "run/demo-20260929-001"
