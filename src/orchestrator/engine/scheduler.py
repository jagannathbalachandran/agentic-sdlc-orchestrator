"""Threaded scheduler: runs a batch of independent ready stages concurrently
(S5a/S5b, S7a/S7b — both now depend on the same upstream stage instead of
chaining, T6.1) — requirements.md §7.3, closes G-3 (architecture-proposal.md
§3.2.2).

Concurrency safety lives in the callees, not here: `EventLog.append` serializes
itself internally (audit/event_log.py), and `git_ops.commit_all` serializes
concurrent commits on the same working tree — this module just fans work out
to threads and joins, one thread per batch member.
"""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from orchestrator.engine.runner import (
    StageGateFailure,
    StageRunner,
    StageRunRequest,
    StageRunResult,
)
from orchestrator.models.agent_io import AgentCallOutcome, AgentCallResponse
from orchestrator.models.graph import StageSpec, StageStatus

BuildRunner = Callable[[StageSpec], StageRunner]
BuildRequest = Callable[[StageSpec], StageRunRequest]


@dataclass(frozen=True)
class BatchResult:
    """One batch member's spec, paired with what running it produced."""

    spec: StageSpec
    result: StageRunResult


def _run_one(runner: StageRunner, request: StageRunRequest) -> StageRunResult:
    """Run one spec; a gate failure becomes a FAILED result (T7.1's bounded
    retry needs every failure mode to reach it uniformly), not an exception —
    StageRunner.run() itself still raises (tested directly), this is the one
    place that catches it, since fsm.py's retry logic is the caller documented
    to decide what happens next.
    """
    try:
        return runner.run(request)
    except StageGateFailure as exc:
        return StageRunResult(
            status=StageStatus.FAILED,
            response=AgentCallResponse(
                outcome=AgentCallOutcome.ERROR, summary=str(exc), duration_seconds=0.0
            ),
            commit=None,
        )


def run_batch(
    specs: tuple[StageSpec, ...],
    build_runner: BuildRunner,
    build_request: BuildRequest,
) -> tuple[BatchResult, ...]:
    """Run every spec in `specs` to completion.

    A single spec runs directly (no thread-pool overhead); more than one runs
    concurrently, each on its own thread, joined before returning.
    """
    if len(specs) <= 1:
        return tuple(
            BatchResult(spec, _run_one(build_runner(spec), build_request(spec)))
            for spec in specs
        )
    with ThreadPoolExecutor(max_workers=len(specs)) as pool:
        futures = [
            (spec, pool.submit(_run_one, build_runner(spec), build_request(spec)))
            for spec in specs
        ]
        return tuple(BatchResult(spec, future.result()) for spec, future in futures)
