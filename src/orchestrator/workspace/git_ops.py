"""Low-level git command wrappers.

Used by workspace/manager.py now; engine/runner.py's commit hook (T6.1) and
rollback-to-checkpoint (T7.1) will build on the same primitives.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from orchestrator.exceptions import GitCommandError

GIT_COMMAND_TIMEOUT_SECONDS = 30
ORCHESTRATOR_COMMIT_AUTHOR_NAME = "orchestrator"
ORCHESTRATOR_COMMIT_AUTHOR_EMAIL = "orchestrator@localhost"


def run_git(cwd: Path, *args: str) -> str:
    """Run one git command in `cwd`; returns stdout, raises GitCommandError on failure."""
    # args are fixed literals from internal callers below, never untrusted input;
    # "git" is resolved via PATH by design, same as every other git wrapper.
    result = subprocess.run(  # noqa: S603
        ["git", *args],  # noqa: S607
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=GIT_COMMAND_TIMEOUT_SECONDS,
        check=False,
    )
    if result.returncode != 0:
        raise GitCommandError(args, result.returncode, result.stderr)
    return result.stdout.strip()


def init_repo(path: Path) -> None:
    """`git init` a new repository at `path`."""
    path.mkdir(parents=True, exist_ok=True)
    run_git(path, "init", "-q")


def clone_repo(source: Path, dest: Path, ref: str) -> None:
    """Clone `source` into `dest`, then check out `ref` (branch, tag, or commit)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    run_git(dest.parent, "clone", "-q", str(source), str(dest))
    run_git(dest, "checkout", "-q", ref)


def commit_all(path: Path, message: str) -> str:
    """Stage everything and commit as the orchestrator; returns the new commit's SHA."""
    run_git(path, "add", "-A")
    run_git(
        path,
        "-c",
        f"user.name={ORCHESTRATOR_COMMIT_AUTHOR_NAME}",
        "-c",
        f"user.email={ORCHESTRATOR_COMMIT_AUTHOR_EMAIL}",
        "commit",
        "-q",
        "-m",
        message,
    )
    return current_commit(path)


def current_commit(path: Path) -> str:
    """Return the current HEAD commit SHA."""
    return run_git(path, "rev-parse", "HEAD")


def create_branch(path: Path, branch_name: str) -> None:
    """Create and switch to a new branch."""
    run_git(path, "checkout", "-q", "-b", branch_name)
