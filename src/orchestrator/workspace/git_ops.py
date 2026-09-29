"""Low-level git command wrappers.

Used by workspace/manager.py now; engine/runner.py's commit hook (T6.1) and
rollback-to-checkpoint (T7.1) will build on the same primitives.
"""

from __future__ import annotations

import subprocess
import threading
from pathlib import Path

from orchestrator.exceptions import GitCommandError

GIT_COMMAND_TIMEOUT_SECONDS = 30
ORCHESTRATOR_COMMIT_AUTHOR_NAME = "orchestrator"
ORCHESTRATOR_COMMIT_AUTHOR_EMAIL = "orchestrator@localhost"

# Serializes commit_all() process-wide (T6.1, closes G-3). A single orchestrator
# process only ever drives one run at a time, and only that run's own concurrent
# stage branches (S5a/S5b, S7a/S7b) ever call commit_all() from multiple threads
# at once, so one lock for the whole process is sufficient — it just stops two
# of those branches from racing `git add -A && git commit` on the same working
# tree/index.
_COMMIT_LOCK = threading.Lock()


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


def _nothing_staged(path: Path) -> bool:
    """True if `git add -A` staged no changes.

    `git diff --cached --quiet` exits 0 for "no staged differences" and 1 for
    "there are some" — the opposite of `run_git`'s success convention, so this
    checks the raw return code directly instead of going through `run_git`.
    """
    result = subprocess.run(
        ["git", "diff", "--cached", "--quiet"],  # noqa: S607
        cwd=str(path),
        capture_output=True,
        timeout=GIT_COMMAND_TIMEOUT_SECONDS,
        check=False,
    )
    return result.returncode == 0


def commit_all(path: Path, message: str) -> str:
    """Stage everything and commit as the orchestrator; returns the new commit's
    SHA.

    Serialized via `_COMMIT_LOCK` so concurrent stage branches (S5a/S5b, S7a/S7b,
    T6.1) never race `git add -A && git commit` on the same working tree. Because
    `git add -A` is workspace-wide (there's no per-stage path scoping yet — that's
    T6.2's path-partitioning policy), a sibling branch's commit_all call, run
    first, may already have staged *and committed* this branch's files too by the
    time this one acquires the lock. That's not an error: if nothing is left to
    stage, this returns the current HEAD (already covering this branch's changes)
    instead of attempting an empty commit, which `git commit` would otherwise
    reject.
    """
    with _COMMIT_LOCK:
        run_git(path, "add", "-A")
        if _nothing_staged(path):
            return current_commit(path)
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
