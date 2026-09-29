"""Executor protocol: engine code depends only on this (C8-AC1)."""

from __future__ import annotations

from typing import Protocol

from orchestrator.models.agent_io import AgentCallRequest, AgentCallResponse


class Executor(Protocol):
    """How an agent call runs: real (`claude -p`) or mock (recorded fixtures)."""

    def execute(self, request: AgentCallRequest) -> AgentCallResponse:
        """Run one agent call; return its small execution summary (O-4)."""
        ...
