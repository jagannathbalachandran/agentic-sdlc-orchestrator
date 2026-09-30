"""Tests for orchestrator.gates.unchanged_on_retry_gate (item 4, T9.7)."""

from __future__ import annotations

from pathlib import Path

from orchestrator.gates.base import StageContext
from orchestrator.gates.unchanged_on_retry_gate import UnchangedOnRetryGate
from orchestrator.models.graph import StageId
from orchestrator.workspace.git_ops import commit_all, init_repo


def _context(tmp_path: Path, attempt: int) -> StageContext:
    return StageContext(
        run_id="run-1",
        stage_id=StageId.S3_DESIGN,
        attempt=attempt,
        workspace_path=tmp_path,
    )


def test_passes_on_the_first_attempt_regardless_of_content(tmp_path: Path) -> None:
    init_repo(tmp_path)
    (tmp_path / "02-design.md").write_text("original\n", encoding="utf-8")
    commit_all(tmp_path, "S3: stage complete")

    outcome = UnchangedOnRetryGate().check(_context(tmp_path, attempt=1))
    assert outcome.passed is True


def test_fails_on_a_retry_when_the_file_is_byte_for_byte_unchanged(
    tmp_path: Path,
) -> None:
    """The exact real-run failure (item 4): a Design rejection's re-run left
    02-design.md identical to the pre-rejection commit."""
    init_repo(tmp_path)
    (tmp_path / "02-design.md").write_text("original\n", encoding="utf-8")
    commit_all(tmp_path, "S3: stage complete")
    # No further edit — simulating an agent call that reported success but
    # never actually touched the file.

    outcome = UnchangedOnRetryGate().check(_context(tmp_path, attempt=2))
    assert outcome.passed is False
    assert "unchanged" in outcome.details
    assert "attempt 2" in outcome.details


def test_passes_on_a_retry_when_the_file_actually_changed(tmp_path: Path) -> None:
    init_repo(tmp_path)
    (tmp_path / "02-design.md").write_text("original\n", encoding="utf-8")
    commit_all(tmp_path, "S3: stage complete")
    (tmp_path / "02-design.md").write_text("revised per feedback\n", encoding="utf-8")

    outcome = UnchangedOnRetryGate().check(_context(tmp_path, attempt=2))
    assert outcome.passed is True


def test_passes_on_a_retry_when_the_file_does_not_exist_yet(tmp_path: Path) -> None:
    init_repo(tmp_path)
    outcome = UnchangedOnRetryGate().check(_context(tmp_path, attempt=2))
    assert outcome.passed is True
    assert "not found" in outcome.details
