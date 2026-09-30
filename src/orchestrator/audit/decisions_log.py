"""Append-only decisions.jsonl: the run's decision lineage (C10-AC6) — every
answer at a Clarification checkpoint is one of these, not just an
approvals.jsonl entry.
"""

from __future__ import annotations

from pathlib import Path

from orchestrator.models.decisions import Decision


def append_decision(path: Path, decision: Decision) -> None:
    """Append one decision record."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(decision.model_dump_json() + "\n")


def read_decisions(path: Path) -> list[Decision]:
    """Read every decision record, in order."""
    if not path.is_file():
        return []
    return [
        Decision.model_validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def next_decision_id(path: Path, run_id: str) -> str:
    """A simple, deterministic decision ID: `<run_id>-decision-<NNN>`."""
    existing_count = len(read_decisions(path))
    return f"{run_id}-decision-{existing_count + 1:03d}"
