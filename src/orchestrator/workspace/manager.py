"""Workspace manager: greenfield init and existing-repo clone (requirements.md C3).

Closes part of gap G-12: for greenfield, the code baseline *is* the setup commit
made here (`base_ref=None`, no tag/branch existed before the run); for an existing
repo, the code baseline is `base_ref`'s resolved commit.

Venv creation (C3-AC3's "target deps installed in the workspace venv only") is
deferred — not needed until a task actually runs a target's own gates (T5.2/T10).
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from orchestrator.workspace.git_ops import (
    clone_repo,
    commit_all,
    create_branch,
    current_commit,
    init_repo,
)

SETUP_COMMIT_MESSAGE = "S0: workspace setup"


@dataclass(frozen=True)
class WorkspaceInitResult:
    """What preparing a workspace produced — feeds run.json's base_ref/base_commit."""

    workspace_path: Path
    base_ref: str | None
    base_commit: str


def init_greenfield_workspace(
    workspace_path: Path, template_path: Path
) -> WorkspaceInitResult:
    """Copy the approved template into a new repo and make the setup commit."""
    shutil.copytree(template_path, workspace_path, dirs_exist_ok=True)
    init_repo(workspace_path)
    commit_sha = commit_all(workspace_path, SETUP_COMMIT_MESSAGE)
    return WorkspaceInitResult(
        workspace_path=workspace_path, base_ref=None, base_commit=commit_sha
    )


def init_existing_workspace(
    workspace_path: Path, source_repo_path: Path, base_ref: str
) -> WorkspaceInitResult:
    """Clone the target at `base_ref`; base_commit is base_ref's resolved commit."""
    clone_repo(source_repo_path, workspace_path, base_ref)
    commit_sha = current_commit(workspace_path)
    return WorkspaceInitResult(
        workspace_path=workspace_path, base_ref=base_ref, base_commit=commit_sha
    )


def create_run_branch(workspace_path: Path, run_id: str) -> str:
    """Create the `run/<run-id>` branch before any agent executes (C3-AC3, D-5)."""
    branch_name = f"run/{run_id}"
    create_branch(workspace_path, branch_name)
    return branch_name
