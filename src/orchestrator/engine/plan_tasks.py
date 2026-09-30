"""Parses 03-plan.md's own task-line convention (the same shape `gates/
traceability_gate.py`'s `PlanCitationGate` already enforces on S4's exit,
T8.1) into an ordered task list, and 01-requirements.md's `Cites:` lines
into an FR -> REQ map — S5a's real per-task loop (C10-AC2, D-8,
requirements.md §12's "per-task commits") needs both to know which developer
call comes next and what to put in that call's commit trailers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

FR_HEADING = re.compile(r"^##\s+(FR-\d+)\s*$", re.MULTILINE)
TASK_LINE = re.compile(r"^-\s+(T-\d+\.\d+)\s+\((DD-\d+)\):\s*(.+)$", re.MULTILINE)
CITES_LINE = re.compile(r"^Cites:\s*(.+)$", re.MULTILINE)


@dataclass(frozen=True)
class PlanTask:
    """One `- T-n.n (DD-n): <description>` line from 03-plan.md, plus which
    `## FR-n` section it's nested under."""

    task_id: str
    dd_id: str
    fr_id: str
    description: str


def _fr_sections(markdown: str) -> tuple[tuple[str, str], ...]:
    """Every `## FR-n` heading paired with the text up to the next one."""
    headings = list(FR_HEADING.finditer(markdown))
    return tuple(
        (
            match.group(1),
            markdown[
                match.end() : headings[index + 1].start()
                if index + 1 < len(headings)
                else len(markdown)
            ],
        )
        for index, match in enumerate(headings)
    )


def parse_plan_tasks(plan_md: str) -> tuple[PlanTask, ...]:
    """Every task, in the order they appear in the file (top to bottom) —
    S5a's real call order."""
    return tuple(
        PlanTask(
            task_id=task_id, dd_id=dd_id, fr_id=fr_id, description=description.strip()
        )
        for fr_id, body in _fr_sections(plan_md)
        for task_id, dd_id, description in TASK_LINE.findall(body)
    )


def parse_fr_to_req(requirements_md: str) -> dict[str, str]:
    """FR-n -> the first REQ-n it cites (01-requirements.md's own `Cites:`
    line, T8.1) — S5a's commit trailers need the Req, not just the FR."""
    result: dict[str, str] = {}
    for fr_id, body in _fr_sections(requirements_md):
        match = CITES_LINE.search(body)
        if match is None:
            continue
        first = match.group(1).split(",")[0].strip()
        if first:
            result[fr_id] = first
    return result
