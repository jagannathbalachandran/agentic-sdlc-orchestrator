"""End-to-end CLI test (mock executor): a scenario driven to completion
through the real CLI entry point, asserting every C12/C13 artifact this
project actually promises gets produced — not just that the run reaches
`completed` (already proven by test_pause_resume.py).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CLI_SUBPROCESS_TIMEOUT_SECONDS = 30


def _run_cli(orch_home: Path, *args: str) -> subprocess.CompletedProcess[str]:
    # sys.executable and fixed literal args, never untrusted input.
    return subprocess.run(  # noqa: S603
        [
            sys.executable,
            "-m",
            "orchestrator.cli.main",
            "--orch-home",
            str(orch_home),
            *args,
        ],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=CLI_SUBPROCESS_TIMEOUT_SECONDS,
        check=False,
    )


def _extract_run_id(stdout: str) -> str:
    for line in stdout.splitlines():
        if line.startswith("run-id="):
            return line.split("=", 1)[1]
    raise AssertionError(f"no run-id line found in: {stdout!r}")


def _read_events(path: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_a_full_mock_run_produces_every_c12_c13_artifact(tmp_path: Path) -> None:
    orch_home = tmp_path / "orch-home"
    project = "demo-project"
    scenario_id = "a-scenario-with-no-fixtures"

    register_result = _run_cli(
        orch_home, "register", project, "https://example.com/demo.git"
    )
    assert register_result.returncode == 0, register_result.stderr

    first = _run_cli(orch_home, "run", project, scenario_id, "--mock")
    assert first.returncode == 0, first.stderr
    run_id = _extract_run_id(first.stdout)

    second = _run_cli(orch_home, "approve", project, run_id, "--comment", "looks good")
    assert second.returncode == 0, second.stderr
    assert "awaiting_approval (release)" in second.stdout

    third = _run_cli(orch_home, "approve", project, run_id, "--comment", "ship it")
    assert third.returncode == 0, third.stderr
    assert f"run {run_id}: completed" in third.stdout

    run_directory = orch_home / "runs" / project / run_id
    workspace = orch_home / "workspaces" / project / run_id

    events = _read_events(run_directory / "events.jsonl")
    event_types = {event["event_type"] for event in events}
    assert "gate_result" in event_types
    assert "policy_result" in event_types
    assert "run_terminal" in event_types
    terminal_events = [e for e in events if e["event_type"] == "run_terminal"]
    assert terminal_events[-1]["payload"] == {"terminal_state": "completed"}

    assert (run_directory / "metrics.json").is_file()
    assert (run_directory / "report.md").is_file()
    assert (run_directory / "pr-description.md").is_file()
    assert (workspace / "traceability.md").is_file()

    metrics = json.loads((run_directory / "metrics.json").read_text(encoding="utf-8"))
    assert metrics["run_success"] is True

    report = (run_directory / "report.md").read_text(encoding="utf-8")
    assert run_id in report
    pr_description = (run_directory / "pr-description.md").read_text(encoding="utf-8")
    assert run_id in pr_description
