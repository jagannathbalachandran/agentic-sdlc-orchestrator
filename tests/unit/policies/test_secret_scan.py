"""Tests for orchestrator.policies.secret_scan (C6-AC1, architecture-proposal.md G-7)."""

from __future__ import annotations

from pathlib import Path

from orchestrator.policies.base import FileChange, WorkspaceDiff
from orchestrator.policies.secret_scan import SecretScanPolicy

PATTERNS = (
    "AKIA[0-9A-Z]{16}",
    "(?i)api[_-]?key\\s*[:=]\\s*['\"][A-Za-z0-9_\\-]{16,}['\"]",
)


def _diff(files: tuple[FileChange, ...]) -> WorkspaceDiff:
    return WorkspaceDiff(
        workspace_path=Path("/workspace"),
        base_commit="base",
        head_commit="head",
        current_branch="run/demo",
        files=files,
    )


def test_passes_when_no_added_line_matches_a_secret_pattern() -> None:
    diff = _diff(
        (FileChange(path="src/app.py", added_lines=("x = 1",), removed_lines=()),)
    )
    result = SecretScanPolicy(PATTERNS).check(diff)
    assert result.passed
    assert result.outcome.value == "ok"


def test_flags_an_aws_access_key_as_critical() -> None:
    diff = _diff(
        (
            FileChange(
                path="src/app.py",
                added_lines=("AKIAABCDEFGHIJKLMNOP",),
                removed_lines=(),
            ),
        )
    )
    result = SecretScanPolicy(PATTERNS).check(diff)
    assert not result.passed
    assert result.outcome.value == "critical"
    assert result.violations


def test_flags_an_api_key_assignment_as_critical() -> None:
    diff = _diff(
        (
            FileChange(
                path="src/config.py",
                added_lines=('api_key = "sk-abcdefghijklmnopqrstuvwx"',),
                removed_lines=(),
            ),
        )
    )
    result = SecretScanPolicy(PATTERNS).check(diff)
    assert not result.passed
    assert result.outcome.value == "critical"


def test_only_scans_added_lines_not_removed_ones() -> None:
    diff = _diff(
        (
            FileChange(
                path="src/app.py",
                added_lines=("x = 1",),
                removed_lines=("AKIAABCDEFGHIJKLMNOP",),
            ),
        )
    )
    result = SecretScanPolicy(PATTERNS).check(diff)
    assert result.passed
