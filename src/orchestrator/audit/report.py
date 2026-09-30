"""report.md generation (requirements.md C12): a human-readable summary of one
run, assembled from its own `GraphState` and computed `Metrics` — the same
generated-not-agent-written stance as `audit/traceability.py`.
"""

from __future__ import annotations

from orchestrator.audit.metrics import Metrics
from orchestrator.models.graph import GraphState, StageResult

_METRIC_ROWS: tuple[tuple[str, str], ...] = (
    ("Run success", "run_success"),
    ("Stage first-pass rate", "stage_first_pass_rate"),
    ("Retry count", "retry_count"),
    ("Rollback count", "rollback_count"),
    ("MTTR (seconds)", "mttr_seconds"),
    ("End-to-end latency (seconds)", "end_to_end_latency_seconds"),
    ("Human wait (seconds)", "human_wait_seconds"),
    (
        "End-to-end latency excluding human wait (seconds)",
        "end_to_end_latency_excluding_human_wait_seconds",
    ),
)


def _stage_row(result: StageResult) -> str:
    commits = ", ".join(sha[:8] for sha in result.commits) or "-"
    return (
        f"| {result.stage_id.value} | {result.status.value} "
        f"| {result.attempts} | {commits} |"
    )


def _metrics_section(metrics: Metrics) -> list[str]:
    lines = ["## Metrics", "", "| Metric | Value |", "|---|---|"]
    lines.extend(
        f"| {label} | {getattr(metrics, field)} |" for label, field in _METRIC_ROWS
    )
    return lines


def generate_report(graph_state: GraphState, metrics: Metrics) -> str:
    """Assemble `report.md`: run identity, terminal state, per-stage status,
    and the run's computed metrics.
    """
    terminal_state = (
        graph_state.terminal_state.value
        if graph_state.terminal_state
        else "in progress"
    )
    lines = [
        "# Run report",
        "",
        f"- Run ID: {graph_state.run_id}",
        f"- Scenario: {graph_state.scenario_id}",
        f"- Outcome: {terminal_state}",
        "",
        "## Stages",
        "",
        "| Stage | Status | Attempts | Commits |",
        "|---|---|---|---|",
    ]
    lines.extend(_stage_row(result) for result in graph_state.stages.values())
    lines.append("")
    lines.extend(_metrics_section(metrics))
    return "\n".join(lines) + "\n"
