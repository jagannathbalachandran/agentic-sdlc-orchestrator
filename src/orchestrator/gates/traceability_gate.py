"""Citation gates (requirements.md C10-AC1): every FR cites the REQ it derives
from; every DD cites >=1 FR; every task cites >=1 DD and sits under >=1 FR.

Each gate reads only its own stage's output file — audit/traceability.py
assembles the full FR -> AC -> DD -> task -> commit -> test chain across
files, at Join S7. The citation convention: a top-level `## <ID>` heading,
followed (before the next such heading) by a `Cites: <ID>[, <ID>...]` line —
except 03-plan.md, whose existing convention already encodes both facts task
citations need (a task line's own `(DD-n)` citation, nested under its `## FR-n`
heading), so that gate parses the existing shape rather than requiring a new
`Cites:` line there too.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from orchestrator.gates.base import StageContext
from orchestrator.models.graph import GateOutcome

FR_HEADING = re.compile(r"^##\s+(FR-\d+)\s*$", re.MULTILINE)
DD_HEADING = re.compile(r"^##\s+(DD-\d+)\s*$", re.MULTILINE)
CITES_LINE = re.compile(r"^Cites:\s*(.+)$", re.MULTILINE)
TASK_LINE = re.compile(r"^-\s+T-\d+\.\d+\s+\(DD-\d+\):", re.MULTILINE)


def _sections(text: str, heading: re.Pattern[str]) -> dict[str, str]:
    """Map each heading ID to the text between it and the next same heading."""
    matches = list(heading.finditer(text))
    return {
        match.group(1): text[
            match.end() : matches[i + 1].start() if i + 1 < len(matches) else len(text)
        ]
        for i, match in enumerate(matches)
    }


def _cited_ids(section_text: str) -> tuple[str, ...]:
    match = CITES_LINE.search(section_text)
    if match is None:
        return ()
    return tuple(part.strip() for part in match.group(1).split(",") if part.strip())


@dataclass(frozen=True)
class RequirementsCitationGate:
    """S1 exit gate: every FR cites the REQ it derives from."""

    gate_name: str = "fr_cites_req"
    relative_path: str = "01-requirements.md"

    def check(self, context: StageContext) -> GateOutcome:
        path = context.workspace_path / self.relative_path
        if not path.is_file():
            return GateOutcome(
                gate_name=self.gate_name,
                passed=False,
                details=f"{self.relative_path} not found",
            )
        sections = _sections(path.read_text(encoding="utf-8"), FR_HEADING)
        missing = [fr for fr, body in sections.items() if not _cited_ids(body)]
        if missing:
            return GateOutcome(
                gate_name=self.gate_name,
                passed=False,
                details=f"missing 'Cites: REQ-n' for {', '.join(missing)}",
            )
        return GateOutcome(
            gate_name=self.gate_name,
            passed=True,
            details=f"{len(sections)} FR(s) cite a REQ",
        )


@dataclass(frozen=True)
class DesignCitationGate:
    """S3 exit gate: every DD cites at least one FR."""

    gate_name: str = "dd_cites_fr"
    relative_path: str = "02-design.md"

    def check(self, context: StageContext) -> GateOutcome:
        path = context.workspace_path / self.relative_path
        if not path.is_file():
            return GateOutcome(
                gate_name=self.gate_name,
                passed=False,
                details=f"{self.relative_path} not found",
            )
        sections = _sections(path.read_text(encoding="utf-8"), DD_HEADING)
        missing = [dd for dd, body in sections.items() if not _cited_ids(body)]
        if missing:
            return GateOutcome(
                gate_name=self.gate_name,
                passed=False,
                details=f"missing 'Cites: FR-n' for {', '.join(missing)}",
            )
        return GateOutcome(
            gate_name=self.gate_name,
            passed=True,
            details=f"{len(sections)} DD(s) cite an FR",
        )


@dataclass(frozen=True)
class PlanCitationGate:
    """S4 exit gate: every task cites at least one DD and sits under an FR."""

    gate_name: str = "task_cites_dd_under_fr"
    relative_path: str = "03-plan.md"

    def check(self, context: StageContext) -> GateOutcome:
        path = context.workspace_path / self.relative_path
        if not path.is_file():
            return GateOutcome(
                gate_name=self.gate_name,
                passed=False,
                details=f"{self.relative_path} not found",
            )
        text = path.read_text(encoding="utf-8")
        sections = _sections(text, FR_HEADING)
        if not sections:
            return GateOutcome(
                gate_name=self.gate_name, passed=False, details="no FR sections found"
            )
        empty = [fr for fr, body in sections.items() if not TASK_LINE.search(body)]
        if empty:
            return GateOutcome(
                gate_name=self.gate_name,
                passed=False,
                details=f"no task citing a DD found under {', '.join(empty)}",
            )
        return GateOutcome(
            gate_name=self.gate_name,
            passed=True,
            details=f"{len(sections)} FR section(s) have >=1 task citing a DD",
        )
