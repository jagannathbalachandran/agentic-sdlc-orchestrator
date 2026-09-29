"""CLI entry point: argument parsing and command dispatch."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from orchestrator.cli.commands import register, run, validate
from orchestrator.registry import resolve_project

ORCH_HOME_ENV_VAR = "ORCH_HOME"
DEFAULT_ORCH_HOME_DIRNAME = ".orchestrator"


def default_orch_home() -> Path:
    """~/.orchestrator/, or $ORCH_HOME if set (requirements.md §8)."""
    override = os.environ.get(ORCH_HOME_ENV_VAR)
    if override:
        return Path(override)
    return Path.home() / DEFAULT_ORCH_HOME_DIRNAME


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level parser with every registered subcommand attached."""
    parser = argparse.ArgumentParser(prog="orchestrator")
    parser.add_argument(
        "--orch-home",
        default=None,
        help="Override ORCH_HOME (default: ~/.orchestrator or $ORCH_HOME)",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    register.add_subparser(subparsers)
    validate.add_subparser(subparsers)
    run.add_subparser(subparsers)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Parse argv and dispatch to the selected command's handler."""
    parser = build_parser()
    args = parser.parse_args(argv)
    orch_home = Path(args.orch_home) if args.orch_home else default_orch_home()

    if args.command == register.COMMAND_NAME:
        return register.handle(args, orch_home)
    if args.command == validate.COMMAND_NAME:
        return validate.handle(
            args, lookup_project=lambda name: resolve_project(orch_home, name)
        )
    if args.command == run.COMMAND_NAME:
        return run.handle(args, orch_home)
    parser.error(f"unknown command: {args.command}")


if __name__ == "__main__":
    sys.exit(main())
