"""Tests for orchestrator.executors.real, using a patched subprocess.Popen.

Covers the DoD's three cases (timeout, malformed summary, well-formed summary)
plus the command/env-building helpers directly. The two live claude -p tests
(smoke call, timeout) are recorded separately in docs/build-notes.md, not here
— they need a real claude installation and network access.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from orchestrator.executors.real import (
    RealExecutor,
    _build_command,
    _build_env,
    _venv_bin_dir,
)
from orchestrator.models.agent_io import AgentCallOutcome, AgentCallRequest
from orchestrator.profiles.loader import load_profile

ANALYST_PROFILE_TOML = """
name = "analyst"
persona = "You are a terse requirements analyst."
responsibilities = "Derive FRs with acceptance criteria."
output_contract = "Reply with {summary, produced_ids, files_written}."
"""

DEVELOPER_PROFILE_TOML = """
name = "developer"
persona = "You are a developer."
responsibilities = "Implement tasks with unit tests."
output_contract = "Reply with a JSON summary."
enabled_tools = ["Bash"]
allowed_tool_patterns = ["Write", "Edit", "Read", "Bash(python -m pytest *)"]
"""


def _profiles_root(tmp_path: Path) -> Path:
    root = tmp_path / "profiles"
    root.mkdir(exist_ok=True)
    (root / "analyst.toml").write_text(ANALYST_PROFILE_TOML, encoding="utf-8")
    (root / "developer.toml").write_text(DEVELOPER_PROFILE_TOML, encoding="utf-8")
    return root


def _request(tmp_path: Path, profile_name: str = "analyst") -> AgentCallRequest:
    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    return AgentCallRequest(
        profile_name=profile_name,
        scenario_id="demo-scenario",
        stage="S1",
        rendered_prompt="derive FRs",
        workspace_path=str(workspace),
        timeout_seconds=5,
        budget_usd=0.5,
    )


class _FakePopen:
    """Stands in for subprocess.Popen: returns fixed stdout, never times out."""

    def __init__(self, stdout: str) -> None:
        self._stdout = stdout
        self.returncode = 0
        self.pid = 4242

    def communicate(self, timeout: float | None = None) -> tuple[str, str]:
        del timeout
        return self._stdout, ""

    def wait(self, timeout: float | None = None) -> int:
        del timeout
        return self.returncode


class _TimingOutPopen:
    """Stands in for subprocess.Popen: always raises TimeoutExpired."""

    def __init__(self) -> None:
        self.pid = 4242

    def communicate(self, timeout: float | None = None) -> tuple[str, str]:
        raise subprocess.TimeoutExpired(cmd="claude", timeout=timeout or 0)

    def wait(self, timeout: float | None = None) -> int:
        del timeout
        return -9


def test_venv_bin_dir_matches_the_current_platform() -> None:
    workspace = Path("/some/workspace")
    expected_subdir = "Scripts" if sys.platform == "win32" else "bin"
    assert _venv_bin_dir(workspace) == workspace / ".venv" / expected_subdir


def test_build_env_prepends_the_venv_bin_dir_to_path(tmp_path: Path) -> None:
    env = _build_env(tmp_path)
    assert env["PATH"].startswith(str(_venv_bin_dir(tmp_path)))


def test_build_command_omits_tools_flag_when_profile_enables_no_extra_tools(
    tmp_path: Path,
) -> None:
    loaded = load_profile(_profiles_root(tmp_path) / "analyst.toml")
    request = _request(tmp_path)

    command = _build_command(request, loaded)

    assert "--tools" not in command
    assert "--restricted" in command
    assert request.rendered_prompt in command


def test_build_command_includes_tools_flag_when_profile_enables_bash(
    tmp_path: Path,
) -> None:
    loaded = load_profile(_profiles_root(tmp_path) / "developer.toml")
    request = _request(tmp_path, profile_name="developer")

    command = _build_command(request, loaded)

    assert "--tools" in command
    assert command[command.index("--tools") + 1] == "Write,Edit,Read,Bash"


def test_execute_returns_timeout_outcome_when_the_call_exceeds_its_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "orchestrator.executors.real.subprocess.Popen",
        lambda *args, **kwargs: _TimingOutPopen(),
    )
    monkeypatch.setattr(
        "orchestrator.executors.real._kill_process_tree", lambda process: None
    )

    executor = RealExecutor(_profiles_root(tmp_path))
    response = executor.execute(_request(tmp_path))

    assert response.outcome is AgentCallOutcome.TIMEOUT


def test_execute_returns_invalid_output_when_the_summary_is_not_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    envelope = json.dumps({"is_error": False, "result": "not json at all"})
    monkeypatch.setattr(
        "orchestrator.executors.real.subprocess.Popen",
        lambda *args, **kwargs: _FakePopen(envelope),
    )

    executor = RealExecutor(_profiles_root(tmp_path))
    response = executor.execute(_request(tmp_path))

    assert response.outcome is AgentCallOutcome.INVALID_OUTPUT
    # T9.9 item 3: a real run recorded outcome=invalid_output with an EMPTY
    # error -- undiagnosable from events alone. The error must now say what
    # failed and show what the agent actually said.
    assert response.summary != ""
    assert "no JSON summary object" in response.summary
    assert "not json at all" in response.summary
    # T9.9 item 2: the transcript must carry the agent's raw reply text, not
    # only the (failed) parsed summary.
    assert response.raw_reply == "not json at all"


def test_execute_returns_invalid_output_when_the_outer_envelope_is_not_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "orchestrator.executors.real.subprocess.Popen",
        lambda *args, **kwargs: _FakePopen("not json"),
    )

    executor = RealExecutor(_profiles_root(tmp_path))
    response = executor.execute(_request(tmp_path))

    assert response.outcome is AgentCallOutcome.INVALID_OUTPUT
    assert response.summary != ""
    assert "not valid JSON" in response.summary
    assert response.raw_reply == "not json"


def test_execute_extracts_the_last_json_object_from_a_reply_with_surrounding_prose(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T9.9 item 4: summary parsing must tolerate prose before/after the
    JSON summary, not require the whole reply to be exactly one JSON
    document."""
    reply = (
        "I've implemented the task and run the tests, all green.\n\n"
        'Here is my summary: {"summary": "did the thing", '
        '"produced_ids": ["T-1.1"], "files_written": ["src/thing.py"]}'
    )
    envelope = json.dumps({"is_error": False, "result": reply})
    monkeypatch.setattr(
        "orchestrator.executors.real.subprocess.Popen",
        lambda *args, **kwargs: _FakePopen(envelope),
    )

    executor = RealExecutor(_profiles_root(tmp_path))
    response = executor.execute(_request(tmp_path))

    assert response.outcome is AgentCallOutcome.SUCCESS
    assert response.summary == "did the thing"
    assert response.files_written == ("src/thing.py",)
    assert response.raw_reply == reply


def test_execute_parses_a_well_formed_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result_text = json.dumps(
        {
            "summary": "derived FR-1",
            "produced_ids": ["FR-1"],
            "files_written": ["01-requirements.md"],
        }
    )
    envelope = json.dumps(
        {
            "is_error": False,
            "result": result_text,
            "total_cost_usd": 0.05,
            "session_id": "abc-123",
        }
    )
    monkeypatch.setattr(
        "orchestrator.executors.real.subprocess.Popen",
        lambda *args, **kwargs: _FakePopen(envelope),
    )

    executor = RealExecutor(_profiles_root(tmp_path))
    response = executor.execute(_request(tmp_path))

    assert response.outcome is AgentCallOutcome.SUCCESS
    assert response.summary == "derived FR-1"
    assert response.produced_ids == ("FR-1",)
    assert response.files_written == ("01-requirements.md",)
    assert response.cost_usd == 0.05
    assert response.session_id == "abc-123"
    assert response.raw_reply == result_text


def test_execute_returns_error_outcome_when_the_envelope_flags_is_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    envelope = json.dumps({"is_error": True, "result": "API error: overloaded"})
    monkeypatch.setattr(
        "orchestrator.executors.real.subprocess.Popen",
        lambda *args, **kwargs: _FakePopen(envelope),
    )

    executor = RealExecutor(_profiles_root(tmp_path))
    response = executor.execute(_request(tmp_path))

    assert response.outcome is AgentCallOutcome.ERROR
    assert "overloaded" in response.summary
    assert response.raw_reply == "API error: overloaded"
