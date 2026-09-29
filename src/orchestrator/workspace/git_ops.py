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

# git's well-known empty-tree object, present in every repository — used as a
# diff base when a run's workspace has no commits yet (T6.2's policies need a
# base to diff against even before S1's first real commit exists).
EMPTY_TREE_SHA = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"

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


def current_commit_or_empty_tree(path: Path) -> str:
    """`current_commit`, or `EMPTY_TREE_SHA` if `path` has no commits yet.

    Used to capture a run's diff base at the moment its workspace is first
    prepared (T6.2) — a brand-new `git init`-only repo has no HEAD to resolve.
    """
    try:
        return current_commit(path)
    except GitCommandError:
        return EMPTY_TREE_SHA


def read_file_at_commit(path: Path, commit: str, file_path: str) -> str | None:
    """`file_path`'s content at `commit`, or None if it didn't exist there."""
    try:
        return run_git(path, "show", f"{commit}:{file_path}")
    except GitCommandError:
        return None


def create_branch(path: Path, branch_name: str) -> None:
    """Create and switch to a new branch."""
    run_git(path, "checkout", "-q", "-b", branch_name)


def current_branch(path: Path) -> str:
    """Return the branch currently checked out.

    `symbolic-ref`, not `rev-parse --abbrev-ref HEAD` — the latter needs HEAD
    to resolve to an actual commit and fails on a fresh `git init`-only repo
    (zero commits) with "ambiguous argument 'HEAD'"; `symbolic-ref` resolves
    the *pending* branch name regardless of whether it has any commits yet.
    """
    return run_git(path, "symbolic-ref", "--short", "HEAD")


def ensure_on_branch(path: Path, branch_name: str) -> None:
    """Make `branch_name` the checked-out branch, creating it if needed.

    Idempotent: a no-op if already on it. `drive()` calls this on every call
    (D-5's "create the run branch before any agent executes") so the run
    never stays on whatever branch `init_repo`/a clone left it on.
    """
    if current_branch(path) == branch_name:
        return
    existing = run_git(path, "branch", "--list", branch_name)
    if existing.strip():
        run_git(path, "checkout", "-q", branch_name)
    else:
        create_branch(path, branch_name)
