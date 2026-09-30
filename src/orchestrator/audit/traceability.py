"""traceability.md generation (requirements.md C10-AC3/AC5): FR -> AC -> DD ->
task -> commit -> test, assembled from the run's own deliverable files and git
history — generated, not agent-written (C10-AC3's own wording).

Reuses the same citation convention `gates/traceability_gate.py` enforces
(`## FR-n` / `## DD-n` headings with a `Cites:` line; `03-plan.md`'s existing
`- T-n.n (DD-n):` task-line shape) plus one new convention this module
defines: an acceptance test file is tagged to the AC(s) it verifies with a
`# Traces: FR-n.ACm[, FR-n.ACm...]` comment line (matching requirements.md
S5b's "each tagged with its FR-n.ACm").

Intentionally NOT wired to a real graph stage yet: requirements.md's own
"Join S7" is a distinct row in §7's stage table, but the current fixed graph
(models/graph.py's StageId) has no node for it — S8 simply depends on both
S7a and S7b directly (T6.1). Adding a real Join-S7 stage is a graph-topology
change bigger than this module's own job; this is the generator + backward
trace, fully testable against constructed inputs, ready for whenever that
topology change lands.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from orchestrator.gates.traceability_gate import (
    CITES_LINE,
    DD_HEADING,
    FR_HEADING,
    TASK_LINE_CAPTURING,
    _sections,
)

# AC headings are this module's own convention (T8.1), not shared with any
# gate -- `## FR-n` / `## DD-n` / `Cites:` / task-line all now come from
# gates/traceability_gate.py instead of a separate copy (T9.8): a real run
# found S4's gate and this generator had drifted onto different regexes
# (`\s*$`, bare heading only, here vs. the gate's real `\b.*$`), so a design
# with real `## DD-1: <title>` headings would have produced an empty
# traceability.md even though every citation gate had already passed it.
AC_HEADING = re.compile(r"^###\s+(FR-\d+\.AC\d+)\b.*$", re.MULTILINE)
TEST_TRACES_LINE = re.compile(r"^#\s*Traces:\s*(.+)$", re.MULTILINE)


def _task_line_findall(body: str) -> list[tuple[str, str]]:
    """`(task_id, dd_id)` pairs only -- this module never needs the task's
    description text, unlike `gates.traceability_gate.parse_plan_tasks`."""
    return [(task_id, dd_id) for task_id, dd_id, _ in TASK_LINE_CAPTURING.findall(body)]


def _cited_ids(section_text: str) -> tuple[str, ...]:
    match = CITES_LINE.search(section_text)
    if match is None:
        return ()
    return tuple(part.strip() for part in match.group(1).split(",") if part.strip())


@dataclass(frozen=True)
class CommitInfo:
    """One commit this run made, and the task it belongs to (from its `Task:`
    trailer) — `None` for a commit that never carried one (T8.1's own
    limitation note: S5a's single generic commit doesn't yet)."""

    sha: str
    task_id: str | None = None


@dataclass(frozen=True)
class TraceabilityInputs:
    """Everything `generate_traceability_report`/`backward_trace` need —
    plain text, so tests can construct them directly without a real run."""

    requirements_md: str
    design_md: str
    plan_md: str
    commits: tuple[CommitInfo, ...] = ()
    acceptance_test_files: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class TraceabilityRow:
    """One FR's full chain, plus whatever's missing from it."""

    fr: str
    acs: tuple[str, ...]
    dds: tuple[str, ...]
    tasks: tuple[str, ...]
    commits: tuple[str, ...]
    tests: tuple[str, ...]
    gaps: tuple[str, ...]


def _ac_ids_by_fr(requirements_md: str, fr_ids: set[str]) -> dict[str, list[str]]:
    by_fr: dict[str, list[str]] = {fr: [] for fr in fr_ids}
    for ac_id in AC_HEADING.findall(requirements_md):
        by_fr.setdefault(ac_id.split(".")[0], []).append(ac_id)
    return by_fr


def _dd_ids_by_fr(design_md: str, fr_ids: set[str]) -> dict[str, list[str]]:
    by_fr: dict[str, list[str]] = {fr: [] for fr in fr_ids}
    for dd_id, body in _sections(design_md, DD_HEADING).items():
        for fr_id in _cited_ids(body):
            by_fr.setdefault(fr_id, []).append(dd_id)
    return by_fr


def _tasks_by_fr(plan_md: str, fr_ids: set[str]) -> dict[str, list[tuple[str, str]]]:
    by_fr: dict[str, list[tuple[str, str]]] = {fr: [] for fr in fr_ids}
    for fr_id, body in _sections(plan_md, FR_HEADING).items():
        by_fr.setdefault(fr_id, []).extend(_task_line_findall(body))
    return by_fr


def _tests_by_ac(acceptance_test_files: dict[str, str]) -> dict[str, list[str]]:
    by_ac: dict[str, list[str]] = {}
    for path, content in acceptance_test_files.items():
        match = TEST_TRACES_LINE.search(content)
        if match is None:
            continue
        for ac_id in (part.strip() for part in match.group(1).split(",")):
            by_ac.setdefault(ac_id, []).append(path)
    return by_ac


@dataclass(frozen=True)
class _ChainMaps:
    """The four per-FR lookup maps `_row_for` needs, bundled to stay under the
    project's max-args limit."""

    ac_map: dict[str, list[str]]
    dd_map: dict[str, list[str]]
    task_map: dict[str, list[tuple[str, str]]]
    commits_by_task: dict[str, list[str]]
    tests_by_ac: dict[str, list[str]]


def _row_for(fr: str, maps: _ChainMaps) -> TraceabilityRow:
    acs = tuple(maps.ac_map.get(fr, ()))
    dds = tuple(maps.dd_map.get(fr, ()))
    tasks = tuple(task_id for task_id, _dd in maps.task_map.get(fr, ()))
    commits = tuple(
        sha for task_id in tasks for sha in maps.commits_by_task.get(task_id, ())
    )
    tests = tuple(sorted({path for ac in acs for path in maps.tests_by_ac.get(ac, ())}))
    gaps = [
        f"{fr}: no AC" if not acs else None,
        f"{fr}: no DD" if not dds else None,
        f"{fr}: no task" if not tasks else None,
        f"{fr}: no commit" if tasks and not commits else None,
        f"{fr}: no test" if acs and not tests else None,
    ]
    return TraceabilityRow(
        fr=fr,
        acs=acs,
        dds=dds,
        tasks=tasks,
        commits=commits,
        tests=tests,
        gaps=tuple(gap for gap in gaps if gap is not None),
    )


def generate_traceability_report(inputs: TraceabilityInputs) -> str:
    """Assemble the FR -> AC -> DD -> task -> commit -> test chain and render
    it as markdown, with a `## Gaps` section listing any missing link
    (C10-AC3: "no gaps", generated — never agent-written).
    """
    fr_ids = set(_sections(inputs.requirements_md, FR_HEADING))
    commits_by_task: dict[str, list[str]] = {}
    for commit in inputs.commits:
        if commit.task_id:
            commits_by_task.setdefault(commit.task_id, []).append(commit.sha)
    maps = _ChainMaps(
        ac_map=_ac_ids_by_fr(inputs.requirements_md, fr_ids),
        dd_map=_dd_ids_by_fr(inputs.design_md, fr_ids),
        task_map=_tasks_by_fr(inputs.plan_md, fr_ids),
        commits_by_task=commits_by_task,
        tests_by_ac=_tests_by_ac(inputs.acceptance_test_files),
    )

    rows = tuple(_row_for(fr, maps) for fr in sorted(fr_ids))
    return _render(rows)


def _render(rows: tuple[TraceabilityRow, ...]) -> str:
    lines = [
        "# Traceability",
        "",
        "| FR | AC | DD | Task | Commit | Test |",
        "|---|---|---|---|---|---|",
    ]
    for row in rows:
        lines.append(
            f"| {row.fr} | {', '.join(row.acs) or '-'} | {', '.join(row.dds) or '-'} "
            f"| {', '.join(row.tasks) or '-'} "
            f"| {', '.join(sha[:8] for sha in row.commits) or '-'} "
            f"| {', '.join(row.tests) or '-'} |"
        )
    all_gaps = [gap for row in rows for gap in row.gaps]
    lines.append("")
    lines.append("## Gaps")
    if all_gaps:
        lines.extend(f"- {gap}" for gap in all_gaps)
    else:
        lines.append("None.")
    return "\n".join(lines) + "\n"


@dataclass(frozen=True)
class BackwardTrace:
    """One commit's lineage back to its task, FR and REQ (C10-AC5)."""

    commit_sha: str
    task_id: str | None
    fr_id: str | None
    req_id: str | None


def backward_trace(inputs: TraceabilityInputs, commit_sha: str) -> BackwardTrace:
    """From a commit's own `Task:` trailer, walk task -> FR (via 03-plan.md's
    nesting) -> REQ (via 01-requirements.md's `Cites:` line) — C10-AC5:
    "Backward trace works: from any changed line, git blame + trailers reach
    the task, FR and REQ." (git blame -> the trailer is the caller's job;
    this is the trailer -> task -> FR -> REQ half.)
    """
    commit = next((c for c in inputs.commits if c.sha == commit_sha), None)
    task_id = commit.task_id if commit is not None else None
    if task_id is None:
        return BackwardTrace(
            commit_sha=commit_sha, task_id=None, fr_id=None, req_id=None
        )

    fr_id = next(
        (
            fr
            for fr, body in _sections(inputs.plan_md, FR_HEADING).items()
            if any(
                found_task == task_id for found_task, _dd in _task_line_findall(body)
            )
        ),
        None,
    )
    req_id = None
    if fr_id is not None:
        fr_sections = _sections(inputs.requirements_md, FR_HEADING)
        cited = _cited_ids(fr_sections.get(fr_id, ""))
        req_id = cited[0] if cited else None
    return BackwardTrace(
        commit_sha=commit_sha, task_id=task_id, fr_id=fr_id, req_id=req_id
    )
