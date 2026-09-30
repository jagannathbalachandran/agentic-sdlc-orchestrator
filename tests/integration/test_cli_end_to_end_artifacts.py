"""End-to-end CLI test (mock executor): a scenario driven to completion
through the real CLI entry point, asserting every C12/C13 artifact this
project actually promises gets produced — not just that the run reaches
`completed` (already proven by test_pause_resume.py).

Uses a real, throwaway local target repo (`.orchestrator/project.toml` +
`.orchestrator/scenarios/<id>.toml`, never a registered target repo — see
CLAUDE.md/item 7's own instruction to verify only against throwaway local
repos) so req_id/requirement_text/base_ref genuinely resolve the same way a
real run's would, and includes one Design rejection + re-approval so the
run's decisions.jsonl (item 5) and the retry-budget/unchanged-on-retry gates
(items 1/4) all get exercised for real, through the CLI, not just unit-level.

The throwaway target is deliberately an *existing-codebase* scenario
(`base_ref` set to its own initial commit), not greenfield — greenfield
copies the real `templates/python-service`, whose own `pyproject.toml` and
`scripts/check.py` would make S0/S6 do a real `pip install` and a real
`scripts/check.py` run (CLAUDE.md: "tests never call real Claude or the
network"). A throwaway target with neither file keeps S0's venv step and
S6's command gate both trivially skipped, same as before this test started
resolving a real target at all.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from orchestrator.workspace.git_ops import commit_all, init_repo

REPO_ROOT = Path(__file__).resolve().parents[2]
CLI_SUBPROCESS_TIMEOUT_SECONDS = 60
SCENARIO_ID = "e2e-full-run"

SCENARIO_TOML = f"""
scenario_id = "{SCENARIO_ID}"
req_id = "REQ-042"
requirement_text = "Shorten, redirect, 404 for unknown codes."
base_ref = "HEAD"
inject_fault = false
"""

PROJECT_TOML = """
project_name = "e2e-target"
approved_dependencies = []
"""


def _target_repo(tmp_path: Path) -> Path:
    target = tmp_path / "target-repo"
    scenarios_dir = target / ".orchestrator" / "scenarios"
    scenarios_dir.mkdir(parents=True)
    (scenarios_dir / f"{SCENARIO_ID}.toml").write_text(SCENARIO_TOML, encoding="utf-8")
    (target / ".orchestrator" / "project.toml").write_text(
        PROJECT_TOML, encoding="utf-8"
    )
    init_repo(target)
    commit_all(target, "initial commit")
    return target


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


def _drive_full_run_via_cli(orch_home: Path, project: str, target: Path) -> str:
    """register -> run -> reject Design (with feedback) -> approve Design ->
    approve Release -> completed, all through real CLI subprocess calls.
    Returns the run id. Split out of the test itself to stay under ruff's
    statement-count limit.
    """
    register_result = _run_cli(orch_home, "register", project, str(target))
    assert register_result.returncode == 0, register_result.stderr

    first = _run_cli(orch_home, "run", project, SCENARIO_ID, "--mock")
    assert first.returncode == 0, first.stderr
    assert "awaiting_approval (design)" in first.stdout
    run_id = _extract_run_id(first.stdout)

    # Reject Design with feedback (item 5): S3 re-runs with the feedback and
    # -- given e2e-full-run's own S3-2.json fixture, genuinely revised --
    # passes items 1/4's fresh-retry-budget and unchanged-on-retry gates,
    # landing back at another Design checkpoint (C11-AC3).
    rejected = _run_cli(
        orch_home, "reject", project, run_id, "--comment", "needs more detail"
    )
    assert rejected.returncode == 0, rejected.stderr
    assert "awaiting_approval (design)" in rejected.stdout

    approved_design = _run_cli(
        orch_home, "approve", project, run_id, "--comment", "looks good now"
    )
    assert approved_design.returncode == 0, approved_design.stderr
    assert "awaiting_approval (release)" in approved_design.stdout

    approved_release = _run_cli(
        orch_home, "approve", project, run_id, "--comment", "ship it"
    )
    assert approved_release.returncode == 0, approved_release.stderr
    assert f"run {run_id}: completed" in approved_release.stdout
    return run_id


def test_a_full_mock_run_produces_every_section_11_file(tmp_path: Path) -> None:
    orch_home = tmp_path / "orch-home"
    project = "demo-project"
    target = _target_repo(tmp_path)

    run_id = _drive_full_run_via_cli(orch_home, project, target)

    run_directory = orch_home / "runs" / project / run_id
    workspace = orch_home / "workspaces" / project / run_id

    events = _read_events(run_directory / "events.jsonl")
    event_types = {event["event_type"] for event in events}
    assert "gate_result" in event_types
    assert "policy_result" in event_types
    assert "run_terminal" in event_types
    terminal_events = [e for e in events if e["event_type"] == "run_terminal"]
    assert terminal_events[-1]["payload"] == {"terminal_state": "completed"}

    # requirements.md §11's full run-record file list.
    assert (run_directory / "run.json").is_file()
    assert (run_directory / "scenario.json").is_file()
    assert (run_directory / "config.effective.json").is_file()
    assert (run_directory / "graph.json").is_file()
    assert (run_directory / "artifacts" / "S1" / "manifest.json").is_file()
    assert (run_directory / "artifacts" / "S3" / "manifest.json").is_file()
    assert (run_directory / "decisions.jsonl").is_file()
    assert (run_directory / "approvals.jsonl").is_file()
    assert (run_directory / "events.jsonl").is_file()
    assert (run_directory / "agents" / "S1-1.json").is_file()
    assert (run_directory / "metrics.json").is_file()
    assert (run_directory / "report.md").is_file()
    assert (run_directory / "pr-description.md").is_file()
    assert (workspace / "traceability.md").is_file()

    run_record = json.loads((run_directory / "run.json").read_text(encoding="utf-8"))
    assert run_record["req_id"] == "REQ-042"
    assert run_record["scenario_hash"]
    assert run_record["effective_config_hash"]

    decisions = [
        json.loads(line)
        for line in (run_directory / "decisions.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    assert decisions[0]["choice"] == "reject"
    assert decisions[0]["rationale"] == "needs more detail"

    metrics = json.loads((run_directory / "metrics.json").read_text(encoding="utf-8"))
    assert metrics["run_success"] is True

    report = (run_directory / "report.md").read_text(encoding="utf-8")
    assert run_id in report
    pr_description = (run_directory / "pr-description.md").read_text(encoding="utf-8")
    assert run_id in pr_description
