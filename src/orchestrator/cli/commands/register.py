"""`orchestrator register` command: map a project name to its repo URL."""

from __future__ import annotations

import argparse
from pathlib import Path

from orchestrator.registry import register_project

COMMAND_NAME = "register"


def add_subparser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """Register `register` on the top-level CLI parser."""
    parser = subparsers.add_parser(
        COMMAND_NAME, help="Register a project name -> repo URL mapping."
    )
    parser.add_argument("project", help="Project name")
    parser.add_argument("repo_url", help="Target repo URL")


def handle(args: argparse.Namespace, orch_home: Path) -> int:
    """Run the register command; returns the process exit code."""
    register_project(orch_home, args.project, args.repo_url)
    print(f"registered {args.project} -> {args.repo_url}")
    return 0
