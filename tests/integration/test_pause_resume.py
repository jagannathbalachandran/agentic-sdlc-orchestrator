"""Integration test: two separate CLI subprocess invocations proving state
reload across a process boundary — the core proof for T2.3's pause/resume
design (O-1/O-2, architecture-proposal.md §3.2.1).
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


def test_run_command_across_two_subprocesses_proves_state_reload(
    tmp_path: Path,
) -> None:
    orch_home = tmp_path / "orch-home"
    project = "demo-project"
    scenario_id = "a-scenario-with-no-fixtures"

    register_result = _run_cli(
        orch_home, "register", project, "https://example.com/demo.git"
    )
    assert register_result.returncode == 0, register_result.stderr

    # Process 1: a fresh process runs exactly S0, then exits.
    first = _run_cli(orch_home, "run", project, scenario_id, "--mock")
    assert first.returncode == 0, first.stderr
    assert "ran S0" in first.stdout
    run_id = _extract_run_id(first.stdout)

    graph_path = orch_home / "runs" / project / run_id / "graph.json"
    graph_after_first = json.loads(graph_path.read_text(encoding="utf-8"))
    assert graph_after_first["stages"]["S0"]["status"] == "passed"
    assert "S1" not in graph_after_first["stages"]

    lock_path = orch_home / "locks" / f"{project}.lock"
    assert not lock_path.exists()

    # Process 2: a second, separate process reloads the same run-id from disk
    # and continues with S1 — proving the reload mechanism, not in-memory state.
    second = _run_cli(
        orch_home, "run", project, scenario_id, "--mock", "--run-id", run_id
    )
    assert second.returncode == 0, second.stderr
    assert "ran S1" in second.stdout

    graph_after_second = json.loads(graph_path.read_text(encoding="utf-8"))
    assert graph_after_second["stages"]["S0"]["status"] == "passed"
    assert graph_after_second["stages"]["S1"]["status"] == "passed"
    assert not lock_path.exists()

    workspace = orch_home / "workspaces" / project / run_id
    assert (workspace / "00-source.md").is_file()
    assert (workspace / "01-requirements.md").is_file()

    # A third, separate process reloads again and continues with S2 — the graph
    # now has all nine stages (T3.2); the full run-to-completed path (incl. the
    # Design/Release checkpoints) is covered by the faster unit-level
    # test_end_to_end_real_graph_reaches_completed_through_all_nine_stages in
    # tests/unit/engine/test_fsm.py, not repeated here via subprocess.
    third = _run_cli(
        orch_home, "run", project, scenario_id, "--mock", "--run-id", run_id
    )
    assert third.returncode == 0, third.stderr
    assert "ran S2" in third.stdout
