"""Tests for orchestrator.audit.agent_transcripts (item 3, C8-AC4)."""

from __future__ import annotations

import json
from pathlib import Path

from orchestrator.audit.agent_transcripts import write_transcript
from orchestrator.models.agent_io import (
    AgentCallOutcome,
    AgentCallResponse,
    AgentCallTranscript,
)


def _transcript(**overrides: object) -> AgentCallTranscript:
    base: dict[str, object] = {
        "agent_call_id": "S1-1",
        "run_id": "run-1",
        "stage": "S1",
        "attempt": 1,
        "role": "analyst",
        "profile_version_hash": "deadbeef",
        "prompt": "derive the FRs",
        "response": AgentCallResponse(
            outcome=AgentCallOutcome.SUCCESS,
            summary="wrote 01-requirements.md",
            duration_seconds=1.5,
        ),
    }
    base.update(overrides)
    return AgentCallTranscript(**base)  # type: ignore[arg-type]


def test_write_transcript_creates_the_directory_and_a_call_named_file(
    tmp_path: Path,
) -> None:
    directory = tmp_path / "agents"

    write_transcript(directory, _transcript())

    path = directory / "S1-1.json"
    assert path.is_file()
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["role"] == "analyst"
    assert payload["profile_version_hash"] == "deadbeef"
    assert payload["prompt"] == "derive the FRs"
    assert payload["response"]["outcome"] == "success"
    assert payload["response"]["duration_seconds"] == 1.5


def test_write_transcript_records_task_id_for_a_per_task_call(tmp_path: Path) -> None:
    directory = tmp_path / "agents"

    write_transcript(
        directory,
        _transcript(agent_call_id="S5a-1-T-1.1", stage="S5a", task_id="T-1.1"),
    )

    payload = json.loads((directory / "S5a-1-T-1.1.json").read_text(encoding="utf-8"))
    assert payload["task_id"] == "T-1.1"


def test_write_transcript_overwrites_a_prior_transcript_for_the_same_call_id(
    tmp_path: Path,
) -> None:
    directory = tmp_path / "agents"
    write_transcript(directory, _transcript(prompt="first attempt"))
    write_transcript(directory, _transcript(prompt="second attempt"))

    payload = json.loads((directory / "S1-1.json").read_text(encoding="utf-8"))
    assert payload["prompt"] == "second attempt"
