"""Tests for orchestrator.cli.commands.run — the parts testable without relying
on the CWD-relative config/fixtures paths or a registered project (covered
end to end by tests/integration/test_pause_resume.py instead).
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from orchestrator.cli.commands import run
from orchestrator.cli.commands._common import UnregisteredProjectError, executor_for
from orchestrator.executors.mock import MockExecutor
from orchestrator.executors.real import RealExecutor
from orchestrator.models.run import ExecutorKind


def test_executor_for_mock_returns_the_mock_executor() -> None:
    assert isinstance(executor_for(ExecutorKind.MOCK), MockExecutor)


def test_executor_for_real_returns_the_real_executor() -> None:
    assert isinstance(executor_for(ExecutorKind.REAL), RealExecutor)


def test_handle_raises_for_an_unregistered_project(tmp_path: Path) -> None:
    """C1: `run` defaults to the real executor for a genuinely new run, which
    means resolving the target via the registry first — an unregistered
    project fails there, before any executor is ever touched.
    """
    args = argparse.Namespace(
        project="never-registered",
        scenario_id="s",
        mock=False,
        run_id=None,
        operator="op",
    )
    with pytest.raises(UnregisteredProjectError):
        run.handle(args, tmp_path)
