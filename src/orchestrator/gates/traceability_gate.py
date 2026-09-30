"""Citation gates (requirements.md C10-AC1): every FR cites the REQ it derives
from; every DD cites >=1 FR (and every FR is covered by >=1 DD, S3's own §7
exit condition); every task cites >=1 DD and sits under >=1 FR.

Each gate reads only its own stage's output file (DesignCitationGate also
reads 01-requirements.md, to check FR coverage in the *other* direction) —
audit/traceability.py assembles the full FR -> AC -> DD -> task -> commit ->
test chain across files, at Join S7. The citation convention: a top-level
`## <ID>` heading, optionally followed by `: <title>` or other trailing text
on the same line (a real design's headings are `## DD-1: <title>`, not the
bare `## DD-1` these gates originally only matched — found on a real run,
where every heading in this shape made every citation gate match zero
sections and pass vacuously, T9.7 item 2), then (before the next such
heading) a `Cites: <ID>[, <ID>...]` line — except 03-plan.md, whose existing
convention already encodes both facts task citations need (a task line's own
`(DD-n)` citation, nested under its `## FR-n` heading), so that gate parses
the existing shape rather than requiring a new `Cites:` line there too.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from orchestrator.gates.base import StageContext
from orchestrator.models.graph import GateOutcome

FR_HEADING = re.compile(r"^##\s+(FR-\d+)\b.*$", re.MULTILINE)
DD_HEADING = re.compile(r"^##\s+(DD-\d+)\b.*$", re.MULTILINE)
CITES_LINE = re.compile(r"^Cites:\s*(.+)$", re.MULTILINE)
TASK_LINE = re.compile(r"^-\s+T-\d+\.\d+\s+\(DD-\d+\):", re.MULTILINE)
TASK_LINE_START = re.compile(r"^-\s+(T-\d+\.\d+)\s+\((DD-\d+)\):[ \t]*", re.MULTILINE)


def _sections(text: str, heading: re.Pattern[str]) -> dict[str, str]:
    """Map each heading ID to the text between it and the next same heading."""
    matches = list(heading.finditer(text))
    return {
        match.group(1): text[
            match.end() : matches[i + 1].start() if i + 1 < len(matches) else len(text)
        ]
        for i, match in enumerate(matches)
    }


def _task_entries(body: str) -> tuple[tuple[str, str, str], ...]:
    """Every `- T-n.n (DD-n): <description>` task line in `body`, each
    paired with its FULL description -- from right after the `(DD-n):`
    prefix up to the next task line (or the end of `body`) -- not just its
    first line. A real run's task entries wrapped across multiple lines
    (long descriptions the planner broke onto continuation lines); the
    previous single-line `(.+)$` capture silently truncated every one of
    them, so the developer's prompt lost everything after the first line,
    including which files the task actually touched (T9.9).
    """
    matches = list(TASK_LINE_START.finditer(body))
    return tuple(
        (
            match.group(1),
            match.group(2),
            body[
                match.end() : matches[i + 1].start()
                if i + 1 < len(matches)
                else len(body)
            ].strip(),
        )
        for i, match in enumerate(matches)
    )


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
        if not sections:
            return GateOutcome(
                gate_name=self.gate_name,
                passed=False,
                details=f"no FR sections found in {self.relative_path}",
            )
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
    """S3 exit gate: every DD cites at least one FR, and every FR (from
    01-requirements.md) is covered by at least one DD (§7's own S3 exit
    condition: "every FR covered by >=1 DD" — the reverse direction from
    "every DD cites >=1 FR", and a real run found nothing checked it: a
    design citing FR-1 from four DDs while FR-2/FR-3 had no DD at all still
    passed)."""

    gate_name: str = "dd_cites_fr"
    relative_path: str = "02-design.md"
    requirements_relative_path: str = "01-requirements.md"

    def check(self, context: StageContext) -> GateOutcome:
        path = context.workspace_path / self.relative_path
        if not path.is_file():
            return GateOutcome(
                gate_name=self.gate_name,
                passed=False,
                details=f"{self.relative_path} not found",
            )
        sections = _sections(path.read_text(encoding="utf-8"), DD_HEADING)
        if not sections:
            return GateOutcome(
                gate_name=self.gate_name,
                passed=False,
                details=f"no DD sections found in {self.relative_path}",
            )
        missing = [dd for dd, body in sections.items() if not _cited_ids(body)]
        if missing:
            return GateOutcome(
                gate_name=self.gate_name,
                passed=False,
                details=f"missing 'Cites: FR-n' for {', '.join(missing)}",
            )

        requirements_path = context.workspace_path / self.requirements_relative_path
        if not requirements_path.is_file():
            return GateOutcome(
                gate_name=self.gate_name,
                passed=False,
                details=(
                    f"{self.requirements_relative_path} not found; cannot "
                    "verify every FR is covered by a DD"
                ),
            )
        fr_ids = set(
            _sections(requirements_path.read_text(encoding="utf-8"), FR_HEADING)
        )
        covered = {fr for body in sections.values() for fr in _cited_ids(body)}
        uncovered = sorted(fr_ids - covered)
        if uncovered:
            return GateOutcome(
                gate_name=self.gate_name,
                passed=False,
                details=f"no DD covers {', '.join(uncovered)}",
            )
        return GateOutcome(
            gate_name=self.gate_name,
            passed=True,
            details=f"{len(sections)} DD(s) cite an FR; all {len(fr_ids)} FR(s) covered",
        )


def parse_plan_tasks(plan_md: str) -> tuple[tuple[str, str, str, str], ...]:
    """Every `- T-n.n (DD-n): <description>` task line in `plan_md`, in file
    order, as `(fr_id, task_id, dd_id, description)` — the single source of
    truth for 03-plan.md's task convention. Both `PlanCitationGate` (S4's
    exit gate, below) and `engine/plan_tasks.py` (S5a's per-task loop) call
    this, so they can never drift apart again: a real run found S4's gate
    already using this file's own (correctly `\\b.*$`-tolerant) `FR_HEADING`
    while `engine/plan_tasks.py` kept its own, separate, still-bare-heading-
    only copy — the plan passed S4's gate, then S5a's own parser found "no
    parseable tasks" in the exact same file (T9.8). `description` spans
    every continuation line up to the next task (T9.9) — see `_task_entries`.
    """
    return tuple(
        (fr_id, task_id, dd_id, description)
        for fr_id, body in _sections(plan_md, FR_HEADING).items()
        for task_id, dd_id, description in _task_entries(body)
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
        # Belt-and-braces (T9.8 item 2): fail if the *shared* parser S5a
        # itself will use finds zero tasks, even if the per-FR check above
        # somehow didn't catch it -- a bad plan must be caught here, where
        # the planner can retry, not at S5a with no gate to retry against.
        if not parse_plan_tasks(text):
            return GateOutcome(
                gate_name=self.gate_name,
                passed=False,
                details="no tasks parseable from 03-plan.md",
            )
        return GateOutcome(
            gate_name=self.gate_name,
            passed=True,
            details=f"{len(sections)} FR section(s) have >=1 task citing a DD",
        )
