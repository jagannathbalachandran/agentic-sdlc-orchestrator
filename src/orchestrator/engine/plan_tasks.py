"""Parses 03-plan.md's own task-line convention into an ordered task list,
and 01-requirements.md's `Cites:` lines into an FR -> REQ map — S5a's real
per-task loop (C10-AC2, D-8, requirements.md §12's "per-task commits") needs
both to know which developer call comes next and what to put in that call's
commit trailers.

The actual parsing (`FR_HEADING`, section-splitting, the task-line pattern)
lives in `gates/traceability_gate.py` — this module's own, separate copy of
that regex fell out of sync with the gate's (T9.8): `PlanCitationGate` (S4's
exit gate) matched real `## FR-1: <title>` headings, but this module still
only matched a bare `## FR-1`, so S4 passed a plan S5a then found "no
parseable tasks" in. `parse_plan_tasks` here now wraps `gates.
traceability_gate.parse_plan_tasks` directly, so the two can't drift apart
again — whatever S4's gate accepts is exactly what S5a will parse.
"""

from __future__ import annotations

from dataclasses import dataclass

from orchestrator.gates.traceability_gate import CITES_LINE, FR_HEADING, _sections
from orchestrator.gates.traceability_gate import parse_plan_tasks as _parse_plan_tasks


@dataclass(frozen=True)
class PlanTask:
    """One `- T-n.n (DD-n): <description>` line from 03-plan.md, plus which
    `## FR-n` section it's nested under."""

    task_id: str
    dd_id: str
    fr_id: str
    description: str


def parse_plan_tasks(plan_md: str) -> tuple[PlanTask, ...]:
    """Every task, in the order they appear in the file (top to bottom) —
    S5a's real call order."""
    return tuple(
        PlanTask(task_id=task_id, dd_id=dd_id, fr_id=fr_id, description=description)
        for fr_id, task_id, dd_id, description in _parse_plan_tasks(plan_md)
    )


def parse_fr_to_req(requirements_md: str) -> dict[str, str]:
    """FR-n -> the first REQ-n it cites (01-requirements.md's own `Cites:`
    line, T8.1) — S5a's commit trailers need the Req, not just the FR."""
    result: dict[str, str] = {}
    for fr_id, body in _sections(requirements_md, FR_HEADING).items():
        match = CITES_LINE.search(body)
        if match is None:
            continue
        first = match.group(1).split(",")[0].strip()
        if first:
            result[fr_id] = first
    return result
