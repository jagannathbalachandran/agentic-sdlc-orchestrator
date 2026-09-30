"""Tests for orchestrator.audit.stage_artifacts (item 7, requirements.md
§11 `artifacts/<stage>/`)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from orchestrator.audit.stage_artifacts import write_stage_artifacts


def test_write_stage_artifacts_copies_files_and_records_their_hashes(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    # write_bytes, not write_text: write_text's universal-newlines mode
    # would rewrite \n to \r\n on Windows, making the hash below not match.
    (workspace / "01-requirements.md").write_bytes(b"# FR-1\n")
    artifacts_dir = tmp_path / "artifacts"

    write_stage_artifacts(artifacts_dir, "S1", workspace, ("01-requirements.md",))

    copy_path = artifacts_dir / "S1" / "01-requirements.md"
    assert copy_path.read_text(encoding="utf-8") == "# FR-1\n"
    manifest = json.loads(
        (artifacts_dir / "S1" / "manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["01-requirements.md"] == hashlib.sha256(b"# FR-1\n").hexdigest()


def test_write_stage_artifacts_is_a_no_op_for_an_empty_files_written(
    tmp_path: Path,
) -> None:
    artifacts_dir = tmp_path / "artifacts"

    write_stage_artifacts(artifacts_dir, "S6", tmp_path / "workspace", ())

    assert not artifacts_dir.exists()


def test_write_stage_artifacts_skips_a_reported_file_that_does_not_exist(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    artifacts_dir = tmp_path / "artifacts"

    write_stage_artifacts(artifacts_dir, "S1", workspace, ("missing.md",))

    manifest = json.loads(
        (artifacts_dir / "S1" / "manifest.json").read_text(encoding="utf-8")
    )
    assert manifest == {}


def test_write_stage_artifacts_merges_across_calls_for_the_same_stage(
    tmp_path: Path,
) -> None:
    """S5a's per-task runner calls this once per task -- a later task's
    files must not erase an earlier task's manifest entries."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "a.py").write_text("a", encoding="utf-8")
    (workspace / "b.py").write_text("b", encoding="utf-8")
    artifacts_dir = tmp_path / "artifacts"

    write_stage_artifacts(artifacts_dir, "S5a", workspace, ("a.py",))
    write_stage_artifacts(artifacts_dir, "S5a", workspace, ("b.py",))

    manifest = json.loads(
        (artifacts_dir / "S5a" / "manifest.json").read_text(encoding="utf-8")
    )
    assert set(manifest) == {"a.py", "b.py"}
    assert (artifacts_dir / "S5a" / "a.py").is_file()
    assert (artifacts_dir / "S5a" / "b.py").is_file()
