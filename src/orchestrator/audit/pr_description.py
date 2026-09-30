"""pr-description.md generation (requirements.md C12-AC5): a ready-to-paste PR
description that identifies the run record (run ID and record location), and
(SHOULD) links to the run's folder in the central audit repo.
"""

from __future__ import annotations

from orchestrator.models.graph import GraphState


def _all_commits(graph_state: GraphState) -> tuple[str, ...]:
    return tuple(
        sha for result in graph_state.stages.values() for sha in result.commits
    )


def generate_pr_description(
    graph_state: GraphState,
    run_record_location: str,
    audit_repo_url: str | None = None,
) -> str:
    """C12-AC5: identifies the run record by ID and location; optionally links
    to its folder in the central audit repo.
    """
    lines = [
        f"# {graph_state.scenario_id}",
        "",
        f"Run ID: `{graph_state.run_id}`",
        f"Run record: `{run_record_location}`",
    ]
    if audit_repo_url is not None:
        lines.append(f"Audit repo: {audit_repo_url}")
    lines.append("")

    commits = _all_commits(graph_state)
    lines.append("## Commits")
    lines.append("")
    if commits:
        lines.extend(f"- {sha[:8]}" for sha in commits)
    else:
        lines.append("None.")

    return "\n".join(lines) + "\n"
