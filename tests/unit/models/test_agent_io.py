"""Tests for orchestrator.models.agent_io."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from orchestrator.models.agent_io import (
    AgentCallOutcome,
    AgentCallRequest,
    AgentCallResponse,
)


def test_agent_call_request_accepts_minimal_valid_input(tmp_path: Path) -> None:
    request = AgentCallRequest(
        profile_name="analyst",
        stage="S1",
        rendered_prompt="Derive FRs from the requirement.",
        workspace_path=str(tmp_path),
        timeout_seconds=600,
        budget_usd=0.5,
    )
    assert request.task_id is None


def test_agent_call_response_defaults_are_empty_not_none() -> None:
    response = AgentCallResponse(
        outcome=AgentCallOutcome.SUCCESS,
        duration_seconds=1.5,
    )
    assert response.produced_ids == ()
    assert response.files_written == ()
    assert response.summary == ""


def test_agent_call_response_requires_outcome() -> None:
    with pytest.raises(ValidationError):
        AgentCallResponse(duration_seconds=1.0)  # type: ignore[call-arg]
