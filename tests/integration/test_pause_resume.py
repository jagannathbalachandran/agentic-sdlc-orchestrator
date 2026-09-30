"""Integration test: separate CLI subprocess invocations proving state reload
across a process boundary at a real approval checkpoint — the core proof for
the pause/resume design (O-1/O-2, architecture-proposal.md §3.2.1).

`drive()` loops through pending stages within one call (item 7 / §3.2.1 step 5),
so `run` alone drives all the way to the first checkpoint (Design, after S3) in
one process; a separate `approve` process reloads that state, resolves it, and
loops again to the next checkpoint (Release, after S8); a third process
resolves that and the run completes.
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


def _stage_statuses(graph_path: Path) -> dict[str, str]:
    graph = json.loads(graph_path.read_text(encoding="utf-8"))
    return {stage: entry["status"] for stage, entry in graph["stages"].items()}


def test_run_then_approve_across_separate_processes_proves_state_reload_at_checkpoints(
    tmp_path: Path,
) -> None:
    orch_home = tmp_path / "orch-home"
    project = "demo-project"
    scenario_id = "a-scenario-with-no-fixtures"

    register_result = _run_cli(
        orch_home, "register", project, "https://example.com/demo.git"
    )
    assert register_result.returncode == 0, register_result.stderr

    # Process 1: `run` loops S0-S3 in one process, pausing at Design.
    first = _run_cli(orch_home, "run", project, scenario_id, "--mock")
    assert first.returncode == 0, first.stderr
    assert "awaiting_approval (design)" in first.stdout
    run_id = _extract_run_id(first.stdout)

    graph_path = orch_home / "runs" / project / run_id / "graph.json"
    statuses_after_first = _stage_statuses(graph_path)
    for stage in ("S0", "S1", "S3"):
        assert statuses_after_first[stage] == "passed"
    # S2 skipped for greenfield (C4-AC3) — this run has no registered target,
    # so base_ref is never set, same as a real greenfield run.
    assert statuses_after_first["S2"] == "skipped"
    assert "S4" not in statuses_after_first

    lock_path = orch_home / "locks" / f"{project}.lock"
    assert not lock_path.exists()

    # Process 2: a separate process reloads the same run-id from disk, resolves
    # the Design checkpoint, and loops S4-S8, pausing at Release — proving the
    # reload mechanism at the real pause point, not an artificial one.
    second = _run_cli(orch_home, "approve", project, run_id, "--comment", "looks good")
    assert second.returncode == 0, second.stderr
    assert "awaiting_approval (release)" in second.stdout

    statuses_after_second = _stage_statuses(graph_path)
    for stage in ("S4", "S5a", "S5b", "S6", "S7a", "S7b", "S8"):
        assert statuses_after_second[stage] == "passed"
    assert not lock_path.exists()

    workspace = orch_home / "workspaces" / project / run_id
    assert (workspace / "00-source.md").is_file()
    assert (workspace / "01-requirements.md").is_file()

    # Process 3: a third, separate process reloads again, resolves Release, and
    # the run completes.
    third = _run_cli(orch_home, "approve", project, run_id, "--comment", "ship it")
    assert third.returncode == 0, third.stderr
    assert "run " + run_id + ": completed" in third.stdout
    assert not lock_path.exists()

    graph = json.loads(graph_path.read_text(encoding="utf-8"))
    assert graph["terminal_state"] == "completed"
