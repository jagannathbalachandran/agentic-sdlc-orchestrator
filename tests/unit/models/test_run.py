"""Tests for orchestrator.models.run."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError

from orchestrator.models.run import (
    TERMINAL_RUN_STATES,
    ExecutorKind,
    RunRecord,
    RunState,
)


def _minimal_run_kwargs() -> dict[str, Any]:
    return {
        "run_id": "shorten-greenfield-20260929-001",
        "project": "shortener-greenfield-by-agents",
        "scenario_id": "shorten-greenfield",
        "req_id": "REQ-001",
        "operator": "jagannath",
        "state": RunState.RUNNING,
        "started_at": datetime(2026, 9, 29, 10, 0, 0, tzinfo=UTC),
        "target_url": "https://github.com/example/shortener-greenfield-by-agents",
        "config_commit": "a" * 40,
        "base_commit": "b" * 40,
        "run_branch": "run/shorten-greenfield-20260929-001",
        "orchestrator_version": "0.1.0",
        "executor_kind": ExecutorKind.MOCK,
        "effective_config_hash": "c" * 64,
    }


def test_run_record_accepts_minimal_valid_input() -> None:
    record = RunRecord(**_minimal_run_kwargs())
    assert record.state is RunState.RUNNING
    assert record.completed_at is None


def test_run_record_rejects_malformed_run_id() -> None:
    kwargs = _minimal_run_kwargs()
    kwargs["run_id"] = "not a valid run id"
    with pytest.raises(ValidationError):
        RunRecord(**kwargs)


def test_run_record_rejects_malformed_req_id() -> None:
    kwargs = _minimal_run_kwargs()
    kwargs["req_id"] = "REQ003"
    with pytest.raises(ValidationError):
        RunRecord(**kwargs)


def test_run_record_requires_state_field() -> None:
    kwargs = _minimal_run_kwargs()
    del kwargs["state"]
    with pytest.raises(ValidationError):
        RunRecord(**kwargs)


def test_terminal_run_states_are_exactly_the_four_terminal_states() -> None:
    assert TERMINAL_RUN_STATES == {
        RunState.COMPLETED,
        RunState.FAILED,
        RunState.REJECTED,
        RunState.STOPPED,
    }
