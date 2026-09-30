"""Real executor: `claude -p` subprocess wrapper (O-4 revised, O-6, O-10, ADR-001).

Per-call timeout kills the whole process tree, not just the direct child
(Windows: `taskkill /T /F`; POSIX: the child's own process group) — `claude -p`
can itself spawn further subprocesses, and killing only the `Popen` handle would
leave those running after the orchestrator has already moved on (ADR-001).

Makes plain `python` resolve to the workspace's own venv inside the subprocess
(PATH prepended with the venv's Scripts/bin dir, the same effect a shell
`activate` script has) — this is what the developer/test-engineer profiles'
scoped `Bash(python -m pytest *)` pattern (T4.2) is written against.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from orchestrator.models.agent_io import (
    AgentCallOutcome,
    AgentCallRequest,
    AgentCallResponse,
)
from orchestrator.profiles.loader import LoadedProfile, load_profile
from orchestrator.profiles.render import (
    render_allowed_tools_flag,
    render_system_prompt,
    render_tools_flag,
)

CLAUDE_EXECUTABLE = "claude"
VENV_DIRNAME = ".venv"
WINDOWS_VENV_BIN_DIRNAME = "Scripts"
POSIX_VENV_BIN_DIRNAME = "bin"
PROCESS_TREE_KILL_WAIT_SECONDS = 10


def _venv_bin_dir(workspace: Path) -> Path:
    subdir = (
        WINDOWS_VENV_BIN_DIRNAME if sys.platform == "win32" else POSIX_VENV_BIN_DIRNAME
    )
    return workspace / VENV_DIRNAME / subdir


def _build_env(workspace: Path) -> dict[str, str]:
    env = dict(os.environ)
    env["PATH"] = str(_venv_bin_dir(workspace)) + os.pathsep + env.get("PATH", "")
    return env


def _build_command(request: AgentCallRequest, profile: LoadedProfile) -> list[str]:
    command = [
        CLAUDE_EXECUTABLE,
        "-p",
        request.rendered_prompt,
        "--output-format",
        "json",
        "--restricted",
        "--add-dir",
        request.workspace_path,
        "--allowedTools",
        render_allowed_tools_flag(profile.profile),
        "--permission-mode",
        "acceptEdits",
        "--append-system-prompt",
        render_system_prompt(profile.profile),
        "--max-budget-usd",
        str(request.budget_usd),
    ]
    tools_flag = render_tools_flag(profile.profile)
    if tools_flag is not None:
        command.extend(["--tools", tools_flag])
    return command


def _kill_process_tree(process: subprocess.Popen[str]) -> None:
    """Kill the whole process tree, not just the direct child (ADR-001)."""
    if sys.platform == "win32":
        subprocess.run(  # noqa: S603
            ["taskkill", "/T", "/F", "/PID", str(process.pid)],  # noqa: S607
            check=False,
            capture_output=True,
        )
    else:
        import signal

        os.killpg(os.getpgid(process.pid), signal.SIGKILL)
    process.wait(timeout=PROCESS_TREE_KILL_WAIT_SECONDS)


def _run_subprocess(
    command: list[str], cwd: Path, env: dict[str, str], timeout_seconds: int
) -> tuple[str, int] | None:
    """Run `command`; returns (stdout, returncode), or None if it timed out."""
    popen_kwargs: dict[str, Any] = {}
    if sys.platform == "win32":
        popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        popen_kwargs["start_new_session"] = True

    # command is a fixed-shape list built from profile/request data (rendered
    # prompt text, not shell-interpreted), never untrusted shell input; "claude"
    # is resolved via PATH by design.
    process = subprocess.Popen(  # noqa: S603
        command,
        cwd=str(cwd),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        **popen_kwargs,
    )
    try:
        stdout, _stderr = process.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        _kill_process_tree(process)
        return None
    return stdout, process.returncode


RAW_REPLY_SNIPPET_CHARS = 500


def _extract_last_json_object(text: str) -> dict[str, Any] | None:
    """The last brace-balanced `{...}` object in `text`, parsed — tolerates
    prose before/after the JSON summary (item 4, T9.9): the developer
    profile's own contract says the final message is *only* the JSON, but a
    real reply isn't guaranteed to honor that, and a strict whole-string
    `json.loads` turned "one stray sentence" into a hard invalid_output.
    Scans from the end so a JSON example embedded earlier in the reply
    (e.g. quoted in an explanation) doesn't win over the real, final one.
    """
    depth = 0
    end: int | None = None
    for index in range(len(text) - 1, -1, -1):
        char = text[index]
        if char == "}":
            if depth == 0:
                end = index
            depth += 1
        elif char == "{":
            depth -= 1
            if depth == 0 and end is not None:
                candidate = text[index : end + 1]
                try:
                    parsed = json.loads(candidate)
                except json.JSONDecodeError:
                    end = None
                    continue
                if isinstance(parsed, dict):
                    return parsed
                end = None
    return None


def _invalid_output_response(
    reason: str,
    raw_reply: str,
    duration_seconds: float,
    cost_usd: float | None = None,
    session_id: str | None = None,
) -> AgentCallResponse:
    """A non-empty, diagnosable error (item 3, T9.9): what failed to parse,
    plus a snippet of what the agent actually said — `summary` is what
    `stage_finished`'s own `error` field surfaces (engine/runner.py), so an
    empty one left a failed stage's cause undiagnosable from events alone.
    """
    snippet = raw_reply[:RAW_REPLY_SNIPPET_CHARS]
    return AgentCallResponse(
        outcome=AgentCallOutcome.INVALID_OUTPUT,
        summary=f"{reason}; reply started: {snippet!r}",
        duration_seconds=duration_seconds,
        cost_usd=cost_usd,
        session_id=session_id,
        raw_reply=raw_reply,
    )


def _response_from_envelope(
    envelope: dict[str, Any], duration_seconds: float
) -> AgentCallResponse:
    cost_usd = envelope.get("total_cost_usd")
    session_id = envelope.get("session_id")
    result_text = envelope.get("result")
    raw_reply = result_text if isinstance(result_text, str) else ""

    if envelope.get("is_error"):
        return AgentCallResponse(
            outcome=AgentCallOutcome.ERROR,
            summary=raw_reply or "claude -p reported is_error with no result text",
            duration_seconds=duration_seconds,
            cost_usd=cost_usd,
            session_id=session_id,
            raw_reply=raw_reply,
        )

    if not isinstance(result_text, str):
        return _invalid_output_response(
            "no 'result' text in the claude -p envelope",
            raw_reply,
            duration_seconds,
            cost_usd,
            session_id,
        )

    summary = _extract_last_json_object(result_text)
    if summary is None:
        return _invalid_output_response(
            "no JSON summary object found in the agent's reply",
            raw_reply,
            duration_seconds,
            cost_usd,
            session_id,
        )

    return AgentCallResponse(
        outcome=AgentCallOutcome.SUCCESS,
        summary=str(summary.get("summary", "")),
        produced_ids=tuple(summary.get("produced_ids", ())),
        files_written=tuple(summary.get("files_written", ())),
        high_severity_findings=tuple(summary.get("high_severity_findings", ())),
        blocking_questions=tuple(summary.get("blocking_questions", ())),
        duration_seconds=duration_seconds,
        cost_usd=cost_usd,
        session_id=session_id,
        raw_reply=raw_reply,
    )


class RealExecutor:
    """Executor implementation backed by real `claude -p` subprocess calls.

    Profiles are loaded by name per call (`request.profile_name`), not bound at
    construction — one RealExecutor instance serves every stage in a drive()
    loop, each of which needs a different role's profile.
    """

    def __init__(self, profiles_root: Path) -> None:
        self._profiles_root = profiles_root

    def execute(self, request: AgentCallRequest) -> AgentCallResponse:
        """Run one real agent call and return its small execution summary."""
        profile = load_profile(self._profiles_root / f"{request.profile_name}.toml")
        workspace = Path(request.workspace_path)
        command = _build_command(request, profile)
        env = _build_env(workspace)

        started = time.time()
        outcome = _run_subprocess(command, workspace, env, request.timeout_seconds)
        duration = round(time.time() - started, 2)

        if outcome is None:
            return AgentCallResponse(
                outcome=AgentCallOutcome.TIMEOUT, duration_seconds=duration
            )

        stdout, _returncode = outcome
        try:
            envelope = json.loads(stdout)
        except json.JSONDecodeError as exc:
            return _invalid_output_response(
                f"claude -p's own stdout was not valid JSON: {exc}", stdout, duration
            )
        if not isinstance(envelope, dict):
            return _invalid_output_response(
                "claude -p's own stdout was valid JSON but not an object",
                stdout,
                duration,
            )

        return _response_from_envelope(envelope, duration)
