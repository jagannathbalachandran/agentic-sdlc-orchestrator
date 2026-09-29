"""Tests for orchestrator.workspace.git_ops."""

from __future__ import annotations

from pathlib import Path

import pytest

from orchestrator.exceptions import GitCommandError
from orchestrator.workspace.git_ops import (
    clone_repo,
    commit_all,
    create_branch,
    current_commit,
    init_repo,
    run_git,
)


def _init_repo_with_one_commit(path: Path) -> str:
    init_repo(path)
    (path / "README.md").write_text("# demo\n", encoding="utf-8")
    return commit_all(path, "init")


def test_init_repo_creates_a_git_repository(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    init_repo(repo)
    assert (repo / ".git").is_dir()


def test_commit_all_stages_everything_and_returns_the_new_sha(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    sha = _init_repo_with_one_commit(repo)
    assert len(sha) == 40
    assert current_commit(repo) == sha


def test_create_branch_switches_to_a_new_branch(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo_with_one_commit(repo)
    create_branch(repo, "run/demo-1")
    assert run_git(repo, "branch", "--show-current") == "run/demo-1"


def test_clone_repo_checks_out_the_requested_ref(tmp_path: Path) -> None:
    source = tmp_path / "source"
    first_sha = _init_repo_with_one_commit(source)
    run_git(source, "tag", "baseline")
    (source / "CHANGELOG.md").write_text("v2\n", encoding="utf-8")
    commit_all(source, "second commit")

    dest = tmp_path / "clone"
    clone_repo(source, dest, "baseline")

    assert current_commit(dest) == first_sha
    assert not (dest / "CHANGELOG.md").exists()


def test_run_git_raises_git_command_error_on_failure(tmp_path: Path) -> None:
    repo = tmp_path / "not-a-repo"
    repo.mkdir()
    with pytest.raises(GitCommandError):
        run_git(repo, "rev-parse", "HEAD")
