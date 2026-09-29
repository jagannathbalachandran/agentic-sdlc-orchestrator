"""Tests for orchestrator.workspace.git_ops."""

from __future__ import annotations

from pathlib import Path

import pytest

from orchestrator.exceptions import GitCommandError
from orchestrator.workspace.git_ops import (
    EMPTY_TREE_SHA,
    clone_repo,
    commit_all,
    create_branch,
    current_branch,
    current_commit,
    current_commit_or_empty_tree,
    ensure_on_branch,
    init_repo,
    read_file_at_commit,
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


def test_current_commit_or_empty_tree_returns_the_sentinel_for_a_fresh_repo(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    init_repo(repo)
    assert current_commit_or_empty_tree(repo) == EMPTY_TREE_SHA


def test_current_commit_or_empty_tree_returns_head_once_a_commit_exists(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    sha = _init_repo_with_one_commit(repo)
    assert current_commit_or_empty_tree(repo) == sha


def test_read_file_at_commit_returns_content_that_existed_at_that_commit(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    sha = _init_repo_with_one_commit(repo)
    # run_git strips trailing whitespace (its established convention), so the
    # source file's trailing newline doesn't survive the round trip.
    assert read_file_at_commit(repo, sha, "README.md") == "# demo"


def test_read_file_at_commit_returns_none_for_a_file_that_did_not_exist_there(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    sha = _init_repo_with_one_commit(repo)
    assert read_file_at_commit(repo, sha, "does-not-exist.md") is None


def test_current_branch_resolves_before_any_commit_exists(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    init_repo(repo)
    # A fresh git init's pending branch name (usually "main") resolves via
    # symbolic-ref even though there's no commit yet to rev-parse.
    assert current_branch(repo)


def test_ensure_on_branch_creates_and_switches_when_the_branch_is_new(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    _init_repo_with_one_commit(repo)
    ensure_on_branch(repo, "run/demo-1")
    assert current_branch(repo) == "run/demo-1"


def test_ensure_on_branch_is_a_no_op_when_already_on_it(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo_with_one_commit(repo)
    ensure_on_branch(repo, "run/demo-1")
    ensure_on_branch(repo, "run/demo-1")
    assert current_branch(repo) == "run/demo-1"


def test_ensure_on_branch_switches_to_an_existing_branch_without_recreating_it(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    _init_repo_with_one_commit(repo)
    create_branch(repo, "run/demo-1")
    run_git(repo, "checkout", "-q", "-b", "other")
    ensure_on_branch(repo, "run/demo-1")
    assert current_branch(repo) == "run/demo-1"
