"""Tests for orchestrator.models.profile."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from orchestrator.models.profile import AgentProfile


def test_agent_profile_accepts_minimal_valid_input() -> None:
    profile = AgentProfile(
        name="analyst",
        persona="You are a terse requirements analyst.",
        responsibilities="Derive FRs with acceptance criteria from the requirement.",
        output_contract="Reply with {summary, produced_ids, files_written}.",
    )
    assert profile.rules == ()
    assert profile.enabled_tools == ()
    assert profile.allowed_tool_patterns == ("Write", "Edit", "Read")


def test_agent_profile_accepts_a_scoped_bash_tool() -> None:
    profile = AgentProfile(
        name="developer",
        persona="You are a developer.",
        responsibilities="Implement tasks with unit tests.",
        output_contract="Reply with {summary, produced_ids, files_written}.",
        enabled_tools=("Bash",),
        allowed_tool_patterns=("Write", "Edit", "Read", "Bash(python -m pytest *)"),
    )
    assert profile.enabled_tools == ("Bash",)
    assert "Bash(python -m pytest *)" in profile.allowed_tool_patterns


def test_agent_profile_requires_output_contract() -> None:
    with pytest.raises(ValidationError):
        AgentProfile(
            name="analyst",
            persona="x",
            responsibilities="y",
        )  # type: ignore[call-arg]
