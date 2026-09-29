"""Tests for orchestrator.policies.main_protection (C6-AC1)."""

from __future__ import annotations

from pathlib import Path

from orchestrator.policies.base import WorkspaceDiff
from orchestrator.policies.main_protection import MainProtectionPolicy


def _diff(branch: str) -> WorkspaceDiff:
    return WorkspaceDiff(
        workspace_path=Path("/workspace"),
        base_commit="base",
        head_commit="head",
        current_branch=branch,
        files=(),
    )


def test_passes_when_on_a_run_branch() -> None:
    result = MainProtectionPolicy().check(_diff("run/demo-20260101-001"))
    assert result.passed
    assert result.outcome.value == "ok"


def test_flags_being_on_main_as_critical() -> None:
    result = MainProtectionPolicy().check(_diff("main"))
    assert not result.passed
    assert result.outcome.value == "critical"
    assert result.violations
