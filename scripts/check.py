"""Single cross-platform quality-gate runner.

Runs ruff check, ruff format --check, mypy --strict, pytest (with coverage),
and pip-audit in order, stopping at the first failing gate.
"""

from __future__ import annotations

import subprocess
import sys

Gate = tuple[str, list[str]]

# Matches requirements.md C15 and pyproject.toml's [tool.coverage.report] fail_under;
# passed explicitly (not left to pytest-cov's implicit config pickup) per the same
# never-trust-implicit-config principle requirements.md §7.4 states for target gates.
COVERAGE_THRESHOLD_PERCENT = 85

GATES: list[Gate] = [
    ("ruff check", [sys.executable, "-m", "ruff", "check", "."]),
    ("ruff format --check", [sys.executable, "-m", "ruff", "format", "--check", "."]),
    (
        "mypy --strict",
        [
            sys.executable,
            "-m",
            "mypy",
            "--strict",
            "src",
            "tests",
            "scripts",
        ],
    ),
    (
        "pytest",
        [
            sys.executable,
            "-m",
            "pytest",
            f"--cov-fail-under={COVERAGE_THRESHOLD_PERCENT}",
        ],
    ),
    ("pip-audit", [sys.executable, "-m", "pip_audit"]),
]


def run_gate(name: str, command: list[str]) -> int:
    print(f"==> Running gate: {name}")
    # command is a fixed, hardcoded argument list (not user input), and shell
    # is not used, so this is not an untrusted-input execution risk.
    result = subprocess.run(command, check=False)  # noqa: S603
    return result.returncode


def main() -> int:
    for name, command in GATES:
        returncode = run_gate(name, command)
        if returncode != 0:
            print(f"FAILED gate: {name} (exit code {returncode})", file=sys.stderr)
            return returncode
    print("All gates passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
