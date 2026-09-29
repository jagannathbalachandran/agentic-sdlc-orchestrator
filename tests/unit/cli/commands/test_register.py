"""Tests for orchestrator.cli.commands.register."""

from __future__ import annotations

import argparse
from pathlib import Path

from orchestrator.cli.commands import register
from orchestrator.registry import resolve_project


def test_handle_registers_the_project(tmp_path: Path) -> None:
    args = argparse.Namespace(project="demo", repo_url="https://example.com/demo.git")
    exit_code = register.handle(args, tmp_path)
    assert exit_code == 0
    assert resolve_project(tmp_path, "demo") == "https://example.com/demo.git"
