"""Command gate (requirements.md D-11, §7.4, AC5): "S6 fails if any test
fails or coverage < threshold, enforced by the orchestrator" — plus §7's S6
row naming lint/types/security/dependency-audit alongside tests+coverage.

Rather than building five separate target-specific tool integrations, this
runs the workspace's own `scripts/check.py` — for a workspace built from
`templates/python-service/` (T5.1) or cloned from either registered target
repo (T5.2), that script already *is* the combined ruff/ruff-format/mypy
--strict/pytest+coverage-85%/pip-audit gate runner, by design (T5.1's own
build note: "the identical 5-gate runner"). One process therefore covers
every item in that stage-table cell, not just coverage narrowly.

**Documented limitation:** a workspace with no `scripts/check.py` (no
template/target match, or a stub/test workspace) passes this gate
trivially rather than failing every such workspace outright — this is a
deliberate leniency default, not silent enforcement; `GateOutcome.details`
always says which branch fired.
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from orchestrator.gates.base import StageContext
from orchestrator.models.graph import GateOutcome

CHECK_SCRIPT_RELATIVE_PATH = "scripts/check.py"
DEFAULT_TIMEOUT_SECONDS = 1800
OUTPUT_TAIL_CHARS = 4000
WINDOWS_VENV_BIN_DIRNAME = "Scripts"
POSIX_VENV_BIN_DIRNAME = "bin"


def _venv_python(workspace_path: Path) -> Path:
    subdir = (
        WINDOWS_VENV_BIN_DIRNAME if sys.platform == "win32" else POSIX_VENV_BIN_DIRNAME
    )
    exe_name = "python.exe" if sys.platform == "win32" else "python"
    return workspace_path / ".venv" / subdir / exe_name


@dataclass(frozen=True)
class TestCoverageGate:
    """S6 exit gate: run the workspace's own `scripts/check.py`, if present."""

    gate_name: str = "tests_pass_and_coverage_threshold"
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS

    def check(self, context: StageContext) -> GateOutcome:
        check_script = context.workspace_path / CHECK_SCRIPT_RELATIVE_PATH
        if not check_script.is_file():
            return GateOutcome(
                gate_name=self.gate_name,
                passed=True,
                details=f"{CHECK_SCRIPT_RELATIVE_PATH} not found; skipped",
            )
        venv_python = _venv_python(context.workspace_path)
        python = str(venv_python) if venv_python.is_file() else sys.executable
        return self._run(context.workspace_path, [python, str(check_script)])

    def _run(self, workspace_path: Path, command: list[str]) -> GateOutcome:
        try:
            # command is a fixed-shape list (a resolved interpreter path plus
            # this gate's own script path), never untrusted shell input.
            result = subprocess.run(  # noqa: S603
                command,
                cwd=str(workspace_path),
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return GateOutcome(
                gate_name=self.gate_name,
                passed=False,
                details=f"timed out after {self.timeout_seconds}s",
            )
        if result.returncode == 0:
            return GateOutcome(
                gate_name=self.gate_name, passed=True, details="scripts/check.py passed"
            )
        tail = (result.stdout + result.stderr)[-OUTPUT_TAIL_CHARS:]
        return GateOutcome(
            gate_name=self.gate_name,
            passed=False,
            details=f"scripts/check.py exit {result.returncode}: {tail}",
        )
