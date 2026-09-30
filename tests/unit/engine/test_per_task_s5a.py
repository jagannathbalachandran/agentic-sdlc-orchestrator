"""End-to-end mock test for S5a's real per-task loop (C10-AC2, D-8,
requirements.md §12 "per-task commits"): N tasks in 03-plan.md -> N separate
developer calls -> N separate commits, each with correct Task/FR/Req/Run/
Stage trailers -- and the traceability report / backward trace both work
against those real commits, not synthetic ones.

Uses a stub graph reusing the real S5a spec's own `commit_strategy=
ONE_PER_TASK` (what actually routes a stage to the per-task runner,
`engine/fsm.py:_build_runner`) but *without* S5b as a concurrent sibling —
isolates the per-task commit mechanism itself from the pre-existing,
documented cross-branch `git add -A` race `workspace/git_ops.py:commit_all`
already describes (also exercised, under real concurrency, by
tests/integration/test_parallel_scheduler.py).
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from orchestrator.audit.traceability import (
    CommitInfo,
    TraceabilityInputs,
    backward_trace,
    generate_traceability_report,
)
from orchestrator.engine.fsm import (
    DriveRequest,
    drive,
    resolve_checkpoint,
    workspace_dir,
)
from orchestrator.executors.mock import MockExecutor
from orchestrator.models.approvals import ApprovalCheckpointKind, ApprovalDecision
from orchestrator.models.graph import CommitStrategy, StageId, StageSpec
from orchestrator.workspace.git_ops import run_git

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURES_ROOT = REPO_ROOT / "fixtures" / "mock"
SCENARIO_ID = "per-task-demo"


def _stub_graph_per_task_s5a() -> dict[StageId, StageSpec]:
    """S0 -> S1 -> [Design pause] -> S3 -> S4 -> S5a (per-task) — every real
    stage S5a actually depends on for its own inputs, S5b deliberately
    excluded so the per-task commit assertions below are race-free.
    """
    return {
        StageId.S0_PREPARE: StageSpec(
            stage_id=StageId.S0_PREPARE,
            requires_agent=False,
            commit_strategy=CommitStrategy.ONE,
        ),
        StageId.S1_REQUIREMENTS: StageSpec(
            stage_id=StageId.S1_REQUIREMENTS,
            owner_profile="analyst",
            depends_on=(StageId.S0_PREPARE,),
            commit_strategy=CommitStrategy.ONE,
            checkpoint_after=ApprovalCheckpointKind.DESIGN,
        ),
        StageId.S3_DESIGN: StageSpec(
            stage_id=StageId.S3_DESIGN,
            owner_profile="architect",
            depends_on=(StageId.S1_REQUIREMENTS,),
            commit_strategy=CommitStrategy.ONE,
        ),
        StageId.S4_PLAN: StageSpec(
            stage_id=StageId.S4_PLAN,
            owner_profile="planner",
            depends_on=(StageId.S3_DESIGN,),
            commit_strategy=CommitStrategy.ONE,
        ),
        StageId.S5A_IMPLEMENT: StageSpec(
            stage_id=StageId.S5A_IMPLEMENT,
            owner_profile="developer",
            depends_on=(StageId.S4_PLAN,),
            commit_strategy=CommitStrategy.ONE_PER_TASK,
        ),
    }


def _request(tmp_path: Path) -> DriveRequest:
    return DriveRequest(
        orch_home=tmp_path, project="demo", run_id="run-1", scenario_id=SCENARIO_ID
    )


def _commit_message(workspace: Path, sha: str) -> str:
    return run_git(workspace, "log", "-1", "--format=%B", sha)


def _drive_to_s5a(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fixtures_root: Path = FIXTURES_ROOT
) -> tuple[Path, tuple[str, ...]]:
    monkeypatch.setattr("orchestrator.engine.fsm.GRAPH", _stub_graph_per_task_s5a())
    executor = MockExecutor(fixtures_root)
    request = _request(tmp_path)

    drive(request, executor=executor, max_run_duration_seconds=3600)
    resolve_checkpoint(request.ref, ApprovalDecision.APPROVE, "approved", "alice", 3600)
    result = drive(request, executor=executor, max_run_duration_seconds=3600)

    workspace = workspace_dir(tmp_path, "demo", "run-1")
    commits = result.graph_state.stages[StageId.S5A_IMPLEMENT].commits
    return workspace, commits


def test_two_plan_tasks_produce_two_distinct_s5a_commits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, commits = _drive_to_s5a(tmp_path, monkeypatch)

    assert len(commits) == 2
    assert len(set(commits)) == 2  # genuinely distinct shas, not the same commit twice
    assert (workspace / "src" / "thing_a.py").is_file()
    assert (workspace / "src" / "thing_b.py").is_file()


def test_each_s5a_commit_carries_the_correct_trailers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, commits = _drive_to_s5a(tmp_path, monkeypatch)

    first_message = _commit_message(workspace, commits[0])
    assert "Task: T-1.1" in first_message
    assert "FR: FR-1" in first_message
    assert "Req: REQ-1" in first_message
    assert "Run: run-1" in first_message
    assert "Stage: S5a" in first_message

    second_message = _commit_message(workspace, commits[1])
    assert "Task: T-1.2" in second_message
    assert "FR: FR-1" in second_message
    assert "Req: REQ-1" in second_message


def test_traceability_report_and_backward_trace_work_from_real_s5a_commits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, commits = _drive_to_s5a(tmp_path, monkeypatch)

    inputs = TraceabilityInputs(
        requirements_md=(workspace / "01-requirements.md").read_text(encoding="utf-8"),
        design_md=(workspace / "02-design.md").read_text(encoding="utf-8"),
        plan_md=(workspace / "03-plan.md").read_text(encoding="utf-8"),
        commits=(
            CommitInfo(sha=commits[0], task_id="T-1.1"),
            CommitInfo(sha=commits[1], task_id="T-1.2"),
        ),
        acceptance_test_files={},
    )

    report = generate_traceability_report(inputs)
    assert "FR-1: no commit" not in report
    assert commits[0][:8] in report
    assert commits[1][:8] in report

    trace = backward_trace(inputs, commit_sha=commits[0])
    assert trace.task_id == "T-1.1"
    assert trace.fr_id == "FR-1"
    assert trace.req_id == "REQ-1"


def test_a_failed_task_call_stops_the_loop_without_committing_later_tasks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T-1.2's fixture is missing everywhere (task-specific *and* the
    `_generic` bare fallback, on every attempt) -- its call fails every
    time, and the loop stops there each attempt: T-1.1 commits, T-1.2 never
    does, even after the bounded retry gives up.
    """
    partial_fixtures_root = tmp_path / "fixtures"
    shutil.copytree(FIXTURES_ROOT, partial_fixtures_root)
    (partial_fixtures_root / SCENARIO_ID / "S5a-T-1.2.json").unlink()
    (partial_fixtures_root / "_generic" / "S5a.json").unlink()

    workspace, commits = _drive_to_s5a(tmp_path, monkeypatch, partial_fixtures_root)

    assert len(commits) == 1
    assert (workspace / "src" / "thing_a.py").is_file()
    assert not (workspace / "src" / "thing_b.py").is_file()
