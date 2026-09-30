"""Per-call agent transcripts: requirements.md §11's `agents/` directory,
C8-AC4 ("every call records role, profile version, prompt, response,
duration, outcome")."""

from __future__ import annotations

from pathlib import Path

from orchestrator.models.agent_io import AgentCallTranscript

TRANSCRIPTS_DIRNAME = "agents"


def write_transcript(directory: Path, transcript: AgentCallTranscript) -> None:
    """Write one call's transcript to `directory/<agent_call_id>.json`."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{transcript.agent_call_id}.json"
    path.write_text(transcript.model_dump_json(indent=2), encoding="utf-8")
