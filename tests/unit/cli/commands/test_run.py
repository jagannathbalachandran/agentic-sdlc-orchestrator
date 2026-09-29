"""Tests for orchestrator.cli.commands.run — the parts testable without relying
on the CWD-relative config/fixtures paths (covered end to end by
tests/integration/test_pause_resume.py instead).
"""

from __future__ import annotations

import argparse
from pathlib import Path

from orchestrator.cli.commands import run


def test_handle_requires_mock_flag_for_now(tmp_path: Path) -> None:
    args = argparse.Namespace(project="demo", scenario_id="s", mock=False, run_id=None)
    exit_code = run.handle(args, tmp_path)
    assert exit_code == 2
