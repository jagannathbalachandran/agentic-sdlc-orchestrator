"""Integration test: S5a/S5b run concurrently against a real git workspace,
proving the threaded scheduler's core safety property (T6.1, closes G-3,
architecture-proposal.md §3.2.2) — engine/scheduler.py's `run_batch` plus
workspace/git_ops.py's commit serialization and audit/event_log.py's own
internal lock, exercised together against real `git` commands, not stubs.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

from orchestrator.engine.fsm import (
    DriveRequest,
    drive,
    resolve_checkpoint,
    workspace_dir,
)
from orchestrator.executors.mock import MockExecutor
from orchestrator.models.agent_io import AgentCallRequest, AgentCallResponse
from orchestrator.models.approvals import ApprovalDecision
from orchestrator.models.graph import StageId
from orchestrator.workspace.git_ops import run_git

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES_ROOT = REPO_ROOT / "fixtures" / "mock"
SCENARIO_WITH_NO_FIXTURES = "a-scenario-with-no-fixtures"
S5_DELAY_SECONDS = 0.15
_TIMED_STAGES = (StageId.S5A_IMPLEMENT.value, StageId.S5B_ACCEPTANCE_TESTS.value)


class _TimingExecutor:
    """Delegates to a real MockExecutor, recording each S5a/S5b call's own
    wall-clock start/end (after an artificial delay) so the test can check
    whether the two intervals actually overlapped — real proof of concurrency,
    unlike inferring it from the whole drive() call's total elapsed time (which
    real git subprocess overhead from other, non-parallel stages would swamp).
    """

    def __init__(self, inner: MockExecutor, delay_seconds: float) -> None:
        self._inner = inner
        self._delay_seconds = delay_seconds
        self._lock = threading.Lock()
        self.intervals: list[tuple[float, float]] = []

    def execute(self, request: AgentCallRequest) -> AgentCallResponse:
        if request.stage in _TIMED_STAGES:
            start = time.monotonic()
            time.sleep(self._delay_seconds)
            end = time.monotonic()
            with self._lock:
                self.intervals.append((start, end))
        return self._inner.execute(request)


def _request(tmp_path: Path) -> DriveRequest:
    return DriveRequest(
        orch_home=tmp_path,
        project="demo",
        run_id="run-1",
        scenario_id=SCENARIO_WITH_NO_FIXTURES,
    )


def test_s5a_and_s5b_run_concurrently_and_both_commit_cleanly_to_a_real_git_repo(
    tmp_path: Path,
) -> None:
    executor = _TimingExecutor(MockExecutor(FIXTURES_ROOT), S5_DELAY_SECONDS)
    request = _request(tmp_path)

    # Drive to the Design pause (S0-S3), approve it, so the next call's batch
    # is exactly S5a+S5b (both depend only on S4, which just passed).
    drive(request, executor=executor, max_run_duration_seconds=3600)
    resolve_checkpoint(
        request.ref, ApprovalDecision.APPROVE, "approved", "tester", 3600
    )

    result = drive(request, executor=executor, max_run_duration_seconds=3600)

    # Both S5a and S5b actually ran, and their delay windows overlapped in
    # wall-clock time — proof they ran on separate threads concurrently, not
    # one after the other.
    assert len(executor.intervals) == 2
    (start_a, end_a), (start_b, end_b) = executor.intervals
    overlap = min(end_a, end_b) - max(start_a, start_b)
    assert overlap > 0

    assert result.graph_state.stages[StageId.S5A_IMPLEMENT].commits
    assert result.graph_state.stages[StageId.S5B_ACCEPTANCE_TESTS].commits

    workspace = workspace_dir(tmp_path, "demo", "run-1")
    assert (workspace / "src" / "placeholder.py").is_file()
    assert (workspace / "tests" / "unit" / "test_placeholder.py").is_file()
    assert (workspace / "tests" / "acceptance" / "test_fr1.py").is_file()

    # Both branches' commits landed on a valid, uncorrupted history: fsck
    # raises GitCommandError on any corruption, and the working tree is clean
    # (nothing left uncommitted after both branches' commit_all calls).
    run_git(workspace, "fsck")
    assert run_git(workspace, "status", "--porcelain") == ""
