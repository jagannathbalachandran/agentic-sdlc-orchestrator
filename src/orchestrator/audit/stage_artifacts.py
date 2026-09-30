"""Per-stage output artifacts with content hashes (requirements.md §11
`artifacts/<stage>/`) — a durable copy of what a stage actually wrote,
independent of the workspace's own git history."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

MANIFEST_FILENAME = "manifest.json"


def write_stage_artifacts(
    artifacts_dir: Path,
    stage: str,
    workspace: Path,
    files_written: tuple[str, ...],
) -> None:
    """Copy each of `files_written` (paths relative to `workspace`) into
    `artifacts_dir/<stage>/`, recording its sha256 in that stage's
    manifest.json. Merges into any manifest already there — S5a's per-task
    runner calls this once per task, not once per stage, so a later task's
    files must not erase an earlier task's entries.
    """
    if not files_written:
        return
    stage_dir = artifacts_dir / stage
    stage_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = stage_dir / MANIFEST_FILENAME
    manifest: dict[str, str] = (
        json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest_path.is_file()
        else {}
    )
    for relative_path in files_written:
        source = workspace / relative_path
        if not source.is_file():
            continue
        content = source.read_bytes()
        destination = stage_dir / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
        manifest[relative_path] = hashlib.sha256(content).hexdigest()
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
    )
