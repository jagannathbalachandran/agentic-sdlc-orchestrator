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

from orchestrator.engine.runner import StageRunner, StageRunRequest, StageRunResult
from orchestrator.models.graph import StageSpec

BuildRunner = Callable[[StageSpec], StageRunner]
BuildRequest = Callable[[StageSpec], StageRunRequest]


@dataclass(frozen=True)
class BatchResult:
    """One batch member's spec, paired with what running it produced."""

    spec: StageSpec
    result: StageRunResult


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
            BatchResult(spec, build_runner(spec).run(build_request(spec)))
            for spec in specs
        )
    with ThreadPoolExecutor(max_workers=len(specs)) as pool:
        futures = [
            (spec, pool.submit(build_runner(spec).run, build_request(spec)))
            for spec in specs
        ]
        return tuple(BatchResult(spec, future.result()) for spec, future in futures)
