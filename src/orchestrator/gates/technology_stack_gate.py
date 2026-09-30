"""S3 exit gate: 02-design.md must name a real technology stack (item 6c,
requirements.md C4/§12) — found missing entirely on the first real
greenfield run: the design named no language, framework, or test client at
all, just interface sketches in a different language than the target
project's own. On failure, S3 retries with this gate's own error as
feedback (the same bounded-retry path every other gate failure already
uses, `engine/fsm.py:_handle_stage_failure`).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from orchestrator.gates.base import StageContext
from orchestrator.models.graph import GateOutcome

STACK_HEADING_PATTERN = re.compile(r"^#{1,6}\s*Technology [Ss]tack\b", re.MULTILINE)
NEXT_HEADING_PATTERN = re.compile(r"^#{1,6}\s", re.MULTILINE)
MIN_STACK_SECTION_LENGTH = 10


def _section_after(content: str, start: int) -> str:
    next_heading = NEXT_HEADING_PATTERN.search(content, start)
    end = next_heading.start() if next_heading else len(content)
    return content[start:end]


@dataclass(frozen=True)
class TechnologyStackGate:
    """S3 exit gate: a non-trivial "Technology stack" section must exist,
    and — when the workspace has a real `pyproject.toml` (every target this
    project drives against is Python) — must actually mention Python,
    rather than just having the heading present with nothing real under it.
    """

    gate_name: str = "technology_stack_named"
    relative_path: str = "02-design.md"

    def check(self, context: StageContext) -> GateOutcome:
        path = context.workspace_path / self.relative_path
        if not path.is_file():
            return GateOutcome(
                gate_name=self.gate_name,
                passed=False,
                details=f"{self.relative_path} not found",
            )
        content = path.read_text(encoding="utf-8")
        match = STACK_HEADING_PATTERN.search(content)
        if match is None:
            return GateOutcome(
                gate_name=self.gate_name,
                passed=False,
                details=(
                    f"no 'Technology stack' section found in {self.relative_path} "
                    "— name a language, framework, and test client"
                ),
            )
        section = _section_after(content, match.end())
        if len(section.strip()) < MIN_STACK_SECTION_LENGTH:
            return GateOutcome(
                gate_name=self.gate_name,
                passed=False,
                details=(
                    "'Technology stack' section is empty or too short to "
                    "name a real stack"
                ),
            )
        pyproject_path = context.workspace_path / "pyproject.toml"
        if pyproject_path.is_file() and "python" not in section.lower():
            return GateOutcome(
                gate_name=self.gate_name,
                passed=False,
                details=(
                    "'Technology stack' section doesn't mention Python, but "
                    "the target's own pyproject.toml is a Python project"
                ),
            )
        return GateOutcome(
            gate_name=self.gate_name,
            passed=True,
            details="technology stack section present and consistent with the target",
        )
