"""Tests for orchestrator.policies.base's compute_diff (T6.2)."""

from __future__ import annotations

from pathlib import Path

from orchestrator.policies.base import compute_diff
from orchestrator.workspace.git_ops import commit_all, ensure_on_branch, init_repo


def test_compute_diff_reports_added_and_removed_lines_per_file(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    init_repo(workspace)
    ensure_on_branch(workspace, "run/demo")
    (workspace / "a.py").write_text("line1\nline2\n", encoding="utf-8")
    base_commit = commit_all(workspace, "base")

    (workspace / "a.py").write_text("line1\nline2 changed\nline3\n", encoding="utf-8")
    (workspace / "b.py").write_text("new file\n", encoding="utf-8")
    commit_all(workspace, "second commit")

    diff = compute_diff(workspace, base_commit)

    assert set(diff.changed_paths) == {"a.py", "b.py"}
    assert diff.current_branch == "run/demo"
    assert diff.base_commit == base_commit
    a_change = next(f for f in diff.files if f.path == "a.py")
    assert "line2 changed" in a_change.added_lines
    assert "line3" in a_change.added_lines
    assert "line2" in a_change.removed_lines
    assert diff.total_changed_lines == sum(
        len(f.added_lines) + len(f.removed_lines) for f in diff.files
    )


def test_compute_diff_against_the_empty_tree_sees_every_committed_file(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    init_repo(workspace)
    (workspace / "only.py").write_text("hello\n", encoding="utf-8")
    commit_all(workspace, "first ever commit")

    empty_tree_sha = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
    diff = compute_diff(workspace, empty_tree_sha)

    assert diff.changed_paths == ("only.py",)
