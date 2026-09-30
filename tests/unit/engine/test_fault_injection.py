"""G-16 fault injection, redesigned so it's actually recoverable under the
real S6 command gate: the orchestrator mutates one small, real behavior in a
file S5a itself just wrote under src/ (not a standalone always-failing test
under tests/acceptance/, which the developer fix call couldn't even write to
and which no fix could ever have made pass). S6's real command gate (`gates/
command_gate.py`, `scripts/check.py`) then fails attempt 1 for real, the fix
call gets that real failure output, and attempt 2 genuinely passes.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from orchestrator.engine.fsm import (
    DriveRequest,
    DriveResult,
    drive,
    run_dir,
    workspace_dir,
)
from orchestrator.executors.mock import MockExecutor
from orchestrator.models.events import EventType
from orchestrator.models.graph import CommitStrategy, StageId, StageSpec, StageStatus
from orchestrator.workspace.git_ops import run_git

SCENARIO_ID = "fault-injection-demo"

CHECK_SCRIPT = (
    "import subprocess\nimport sys\n\n"
    'result = subprocess.run([sys.executable, "-m", "pytest", "tests/unit", "-q"])\n'
    "sys.exit(result.returncode)\n"
)
CALC_SOURCE = (
    '"""A tiny module S5a "wrote" for this test."""\n\n\n'
    "def is_positive(value: int) -> bool:\n"
    "    if value > 0:\n"
    "        return True\n"
    "    return False\n"
)
CALC_TEST = (
    "from src.calc import is_positive\n\n\n"
    "def test_is_positive_true_for_a_positive_number() -> None:\n"
    "    assert is_positive(5) is True\n\n\n"
    "def test_is_positive_false_for_a_non_positive_number() -> None:\n"
    "    assert is_positive(-1) is False\n"
)


def _stub_graph() -> dict[StageId, StageSpec]:
    """S0 (writes scripts/check.py + the plan/requirements files a real S1/
    S3/S4 would have produced) -> S5a (real per-task runner) -> S6 (real
    spec: requires_agent=False, the real TestCoverageGate) — isolates G-16's
    fail -> fix -> pass loop against a genuinely working command gate,
    without needing the rest of the graph.
    """
    return {
        StageId.S0_PREPARE: StageSpec(
            stage_id=StageId.S0_PREPARE, commit_strategy=CommitStrategy.ONE
        ),
        StageId.S5A_IMPLEMENT: StageSpec(
            stage_id=StageId.S5A_IMPLEMENT,
            owner_profile="developer",
            depends_on=(StageId.S0_PREPARE,),
            commit_strategy=CommitStrategy.ONE_PER_TASK,
        ),
        StageId.S6_VERIFY: StageSpec(
            stage_id=StageId.S6_VERIFY,
            depends_on=(StageId.S5A_IMPLEMENT,),
            commit_strategy=CommitStrategy.NONE,
            requires_agent=False,
        ),
    }


def _write_fixture(fixtures_root: Path, stage: str, fixture: dict[str, object]) -> None:
    scenario_dir = fixtures_root / SCENARIO_ID
    scenario_dir.mkdir(parents=True, exist_ok=True)
    (scenario_dir / f"{stage}.json").write_text(json.dumps(fixture), encoding="utf-8")


def _build_fixtures(tmp_path: Path) -> Path:
    fixtures_root = tmp_path / "fixtures"
    _write_fixture(
        fixtures_root,
        "S0",
        {
            "summary": "prepared",
            "produced_ids": [],
            "files_written": ["scripts/check.py", "01-requirements.md", "03-plan.md"],
            "files": {
                "scripts/check.py": CHECK_SCRIPT,
                "01-requirements.md": (
                    "# Requirements\n\n## FR-1\nCites: REQ-1\nbody.\n"
                ),
                "03-plan.md": "# Plan\n\n## FR-1\n- T-1.1 (DD-1): implement is_positive.\n",
            },
        },
    )
    _write_fixture(
        fixtures_root,
        "S5a-T-1.1",
        {
            "summary": "implemented is_positive",
            "produced_ids": ["T-1.1"],
            "files_written": [
                "src/__init__.py",
                "src/calc.py",
                "tests/unit/test_calc.py",
            ],
            "files": {
                "src/__init__.py": "",
                "src/calc.py": CALC_SOURCE,
                "tests/unit/test_calc.py": CALC_TEST,
            },
        },
    )
    # No S5a-2 fixture written here — the fix call (StageRunner.run(),
    # attempt=2, task_id=None) looks it up on its own; tests that need the
    # fix to actually succeed add it themselves.
    return fixtures_root


def _drive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fixtures_root: Path
) -> DriveResult:
    monkeypatch.setattr("orchestrator.engine.fsm.GRAPH", _stub_graph())
    request = DriveRequest(
        orch_home=tmp_path,
        project="demo",
        run_id="run-1",
        scenario_id=SCENARIO_ID,
        inject_fault=True,
    )
    return drive(
        request, executor=MockExecutor(fixtures_root), max_run_duration_seconds=3600
    )


def _read_events(tmp_path: Path) -> list[dict[str, object]]:
    path = run_dir(tmp_path, "demo", "run-1") / "events.jsonl"
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _payload(event: dict[str, object]) -> dict[str, object]:
    payload = event["payload"]
    assert isinstance(payload, dict)
    return payload


def test_a_defect_is_mutated_into_src_after_s5a_and_recorded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixtures_root = _build_fixtures(tmp_path)
    # No S5a-fix fixture for this scenario -> the fix call falls back to the
    # generic fixture (writes an unrelated src/placeholder.py), so it never
    # actually repairs calc.py -> S6 keeps failing until the bounded retry
    # gives up. That's exercised by the next test; this one only checks the
    # mutation + its event, which happen before any of that.
    _drive(tmp_path, monkeypatch, fixtures_root)

    workspace = workspace_dir(tmp_path, "demo", "run-1")
    mutated = (workspace / "src" / "calc.py").read_text(encoding="utf-8")
    assert "return True" not in mutated
    assert mutated.count("return False") == 2  # the original one, plus the flip

    injected = [
        e
        for e in _read_events(tmp_path)
        if e["event_type"] == EventType.FAULT_INJECTED.value
    ]
    assert len(injected) == 1
    assert injected[0]["injected"] is True
    assert injected[0]["stage"] == "S5a"
    payload = injected[0]["payload"]
    assert isinstance(payload, dict)
    assert payload["file"] == "src/calc.py"
    assert "return True" in payload["change"]
    assert "return False" in payload["change"]


def test_s6_fails_for_real_on_attempt_1_via_the_real_command_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixtures_root = _build_fixtures(tmp_path)
    result = _drive(tmp_path, monkeypatch, fixtures_root)

    s6_gate_results = [
        e
        for e in _read_events(tmp_path)
        if e["event_type"] == "gate_result"
        and e["stage"] == "S6"
        and _payload(e)["gate_name"] == "tests_pass_and_coverage_threshold"
    ]
    assert len(s6_gate_results) >= 1
    first_payload = _payload(s6_gate_results[0])
    assert first_payload["passed"] is False
    assert "test_is_positive" in str(first_payload["details"])

    # No working S5a-fix fixture for this scenario -> the fix call's own
    # generic fallback never actually repairs calc.py, so every attempt
    # fails and the bounded retry eventually gives up.
    assert result.graph_state.stages[StageId.S6_VERIFY].status is StageStatus.FAILED


def test_fail_fix_pass_with_the_real_command_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The full loop: S6 attempt 1 fails for real (the mutated src/calc.py);
    the fix call restores it; S6 attempt 2 passes for real."""
    fixtures_root = _build_fixtures(tmp_path)
    _write_fixture(
        fixtures_root,
        "S5a-2",
        {
            "summary": "restored is_positive per the S6 failure output",
            "produced_ids": [],
            "files_written": ["src/calc.py"],
            "files": {"src/calc.py": CALC_SOURCE},
        },
    )

    result = _drive(tmp_path, monkeypatch, fixtures_root)

    assert result.graph_state.stages[StageId.S6_VERIFY].status is StageStatus.PASSED
    assert result.graph_state.stages[StageId.S6_VERIFY].attempts == 2
    assert result.graph_state.fault_injected is True

    workspace = workspace_dir(tmp_path, "demo", "run-1")
    assert "return True" in (workspace / "src" / "calc.py").read_text(encoding="utf-8")

    # The fix commit itself is real, on-branch, with the right trailer.
    fix_commits = run_git(
        workspace, "log", "--format=%H", "--grep=Stage: S5a-fix"
    ).splitlines()
    assert len(fix_commits) == 1
