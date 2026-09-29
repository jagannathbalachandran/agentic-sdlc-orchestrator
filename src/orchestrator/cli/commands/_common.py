"""Shared helpers for CLI commands that touch an existing run."""

from __future__ import annotations

from pathlib import Path

from orchestrator.config.loader import load_defaults_config
from orchestrator.models.graph import GraphState

DEFAULTS_CONFIG_PATH = Path("config/defaults.toml")
FIXTURES_ROOT = Path("fixtures/mock")
SECONDS_PER_MINUTE = 60


def max_run_duration_seconds() -> float:
    """Read the configured run-duration limit and convert it to seconds."""
    defaults = load_defaults_config(DEFAULTS_CONFIG_PATH)
    return defaults.limits.max_run_duration_minutes * SECONDS_PER_MINUTE


def describe(graph_state: GraphState) -> str:
    """One-line human-readable status for CLI output."""
    if graph_state.terminal_state is not None:
        return f"run {graph_state.run_id}: {graph_state.terminal_state.value}"
    if graph_state.pending_checkpoint is not None:
        checkpoint = graph_state.pending_checkpoint.value
        return f"run {graph_state.run_id}: awaiting_approval ({checkpoint})"
    return f"run {graph_state.run_id}: running"
