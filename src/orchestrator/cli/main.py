"""CLI entry point: argument parsing and command dispatch."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Callable
from pathlib import Path

from orchestrator.cli.commands import (
    answer,
    approve,
    register,
    reject,
    rollback,
    run,
    stop,
    validate,
)
from orchestrator.registry import resolve_project

ORCH_HOME_ENV_VAR = "ORCH_HOME"
DEFAULT_ORCH_HOME_DIRNAME = ".orchestrator"

CommandHandler = Callable[[argparse.Namespace, Path], int]


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
    for module in (register, validate, run, approve, reject, answer, stop, rollback):
        module.add_subparser(subparsers)
    return parser


def _validate_handler(args: argparse.Namespace, orch_home: Path) -> int:
    return validate.handle(
        args, lookup_project=lambda name: resolve_project(orch_home, name)
    )


def _handlers() -> dict[str, CommandHandler]:
    return {
        register.COMMAND_NAME: register.handle,
        validate.COMMAND_NAME: _validate_handler,
        run.COMMAND_NAME: run.handle,
        approve.COMMAND_NAME: approve.handle,
        reject.COMMAND_NAME: reject.handle,
        answer.COMMAND_NAME: answer.handle,
        stop.COMMAND_NAME: stop.handle,
        rollback.COMMAND_NAME: rollback.handle,
    }


def main(argv: list[str] | None = None) -> int:
    """Parse argv and dispatch to the selected command's handler."""
    parser = build_parser()
    args = parser.parse_args(argv)
    orch_home = Path(args.orch_home) if args.orch_home else default_orch_home()

    handler = _handlers().get(args.command)
    if handler is None:
        parser.error(f"unknown command: {args.command}")
    return handler(args, orch_home)


if __name__ == "__main__":
    sys.exit(main())
