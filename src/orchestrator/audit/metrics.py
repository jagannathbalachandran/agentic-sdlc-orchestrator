"""metrics.json computation (requirements.md C13): everything here is derived
from a run's own `events.jsonl` only (C13-AC1) — no graph.json, no run.json.

Two latency figures cover C13's "stage and agent-call latency": one
`STAGE_STARTED`/`STAGE_FINISHED` pair *is* one agent call (StageRunner.run()
makes exactly one executor call per invocation, engine/runner.py), so
`agent_call_latency_seconds` is keyed per stage+attempt, and
`stage_latency_seconds` is that stage's attempts summed — total wall time a
stage cost the run, retries included.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import BaseModel

from orchestrator.models.events import Event, EventType
from orchestrator.models.run import RunState


@dataclass(frozen=True)
class _StageAttemptSpan:
    stage: str
    attempt: int
    started_at: float
    finished_at: float | None = None
    passed: bool | None = None


def _stage_attempt_spans(events: tuple[Event, ...]) -> list[_StageAttemptSpan]:
    """Pair each `STAGE_STARTED` with its `STAGE_FINISHED` by (stage, attempt).
    A started span with no matching finish (a run that stopped mid-call) is
    kept open-ended (`finished_at=None`) rather than dropped.
    """
    open_spans: dict[tuple[str, int], _StageAttemptSpan] = {}
    closed: list[_StageAttemptSpan] = []
    for event in events:
        if event.stage is None or event.attempt is None:
            continue
        key = (event.stage, event.attempt)
        if event.event_type is EventType.STAGE_STARTED:
            open_spans[key] = _StageAttemptSpan(
                stage=event.stage,
                attempt=event.attempt,
                started_at=event.recorded_at.timestamp(),
            )
        elif event.event_type is EventType.STAGE_FINISHED and key in open_spans:
            span = open_spans.pop(key)
            closed.append(
                _StageAttemptSpan(
                    stage=span.stage,
                    attempt=span.attempt,
                    started_at=span.started_at,
                    finished_at=event.recorded_at.timestamp(),
                    passed=event.payload.get("status") == "passed",
                )
            )
    closed.extend(open_spans.values())
    return closed


def _agent_call_latency_seconds(
    spans: list[_StageAttemptSpan],
) -> dict[str, float]:
    return {
        f"{span.stage}:{span.attempt}": span.finished_at - span.started_at
        for span in spans
        if span.finished_at is not None
    }


def _stage_latency_seconds(spans: list[_StageAttemptSpan]) -> dict[str, float]:
    totals: dict[str, float] = {}
    for span in spans:
        if span.finished_at is None:
            continue
        totals[span.stage] = totals.get(span.stage, 0.0) + (
            span.finished_at - span.started_at
        )
    return totals


def _stage_first_pass_rate(spans: list[_StageAttemptSpan]) -> float | None:
    first_attempts = [
        span for span in spans if span.attempt == 1 and span.passed is not None
    ]
    if not first_attempts:
        return None
    passed = sum(1 for span in first_attempts if span.passed)
    return passed / len(first_attempts)


def _recovery_seconds(stage_spans: list[_StageAttemptSpan]) -> float | None:
    """One stage's failure -> next-success gap, or `None` if it never failed
    or never recovered. `finished_at` is never `None` here — `stage_spans`
    only ever holds closed spans (see `_mttr_seconds`'s filter).
    """
    ordered = sorted(stage_spans, key=lambda span: span.attempt)
    first_failure = next((s for s in ordered if s.passed is False), None)
    if first_failure is None or first_failure.finished_at is None:
        return None
    next_success = next(
        (s for s in ordered if s.passed and s.attempt > first_failure.attempt),
        None,
    )
    if next_success is None or next_success.finished_at is None:
        return None
    return next_success.finished_at - first_failure.finished_at


def _mttr_seconds(spans: list[_StageAttemptSpan]) -> float | None:
    """Mean, over every stage, of (first success's finish) - (that stage's
    first failure's finish) — only for stages that failed at least once and
    later succeeded. `None` when no stage both failed and later recovered.
    """
    by_stage: dict[str, list[_StageAttemptSpan]] = {}
    for span in spans:
        if span.finished_at is not None:
            by_stage.setdefault(span.stage, []).append(span)

    recoveries: list[float] = []
    for stage_spans in by_stage.values():
        recovery = _recovery_seconds(stage_spans)
        if recovery is not None:
            recoveries.append(recovery)

    if not recoveries:
        return None
    return sum(recoveries) / len(recoveries)


def _human_wait_seconds(events: tuple[Event, ...]) -> float:
    """Sum of every `APPROVAL_REQUESTED` -> next `APPROVAL_RECORDED` gap —
    time the run spent blocked on a human, excluded from the "without human
    wait" end-to-end figure.
    """
    total = 0.0
    pending_since: float | None = None
    for event in events:
        if event.event_type is EventType.APPROVAL_REQUESTED:
            pending_since = event.recorded_at.timestamp()
        elif (
            event.event_type is EventType.APPROVAL_RECORDED
            and pending_since is not None
        ):
            total += event.recorded_at.timestamp() - pending_since
            pending_since = None
    return total


def _run_success(events: tuple[Event, ...]) -> bool | None:
    for event in events:
        if event.event_type is EventType.RUN_TERMINAL:
            return event.payload.get("terminal_state") == RunState.COMPLETED.value
        if event.event_type is EventType.STOP:
            return False
    return None


@dataclass(frozen=True)
class Metrics:
    """C13's metric set, computed from one run's events only (C13-AC1)."""

    run_success: bool | None
    stage_first_pass_rate: float | None
    retry_count: int
    rollback_count: int
    mttr_seconds: float | None
    end_to_end_latency_seconds: float | None
    human_wait_seconds: float
    end_to_end_latency_excluding_human_wait_seconds: float | None
    stage_latency_seconds: dict[str, float] = field(default_factory=dict)
    agent_call_latency_seconds: dict[str, float] = field(default_factory=dict)


class MetricsModel(BaseModel):
    """`Metrics`, as written to metrics.json."""

    run_success: bool | None
    stage_first_pass_rate: float | None
    retry_count: int
    rollback_count: int
    mttr_seconds: float | None
    end_to_end_latency_seconds: float | None
    human_wait_seconds: float
    end_to_end_latency_excluding_human_wait_seconds: float | None
    stage_latency_seconds: dict[str, float]
    agent_call_latency_seconds: dict[str, float]


def compute_metrics(events: list[Event]) -> Metrics:
    """C13: run success rate, stage first-pass rate, retry/rollback
    frequency, MTTR, end-to-end latency with/without human wait, and
    stage/agent-call latency — every figure derived from `events` alone.
    """
    ordered = tuple(sorted(events, key=lambda event: event.sequence))
    spans = _stage_attempt_spans(ordered)

    end_to_end = None
    if ordered:
        end_to_end = (
            ordered[-1].recorded_at.timestamp() - ordered[0].recorded_at.timestamp()
        )
    human_wait = _human_wait_seconds(ordered)

    return Metrics(
        run_success=_run_success(ordered),
        stage_first_pass_rate=_stage_first_pass_rate(spans),
        retry_count=sum(1 for e in ordered if e.event_type is EventType.RETRY),
        rollback_count=sum(1 for e in ordered if e.event_type is EventType.ROLLBACK),
        mttr_seconds=_mttr_seconds(spans),
        end_to_end_latency_seconds=end_to_end,
        human_wait_seconds=human_wait,
        end_to_end_latency_excluding_human_wait_seconds=(
            None if end_to_end is None else end_to_end - human_wait
        ),
        stage_latency_seconds=_stage_latency_seconds(spans),
        agent_call_latency_seconds=_agent_call_latency_seconds(spans),
    )


def metrics_to_model(metrics: Metrics) -> MetricsModel:
    """`Metrics` -> the pydantic model `atomic_write_json` needs for metrics.json."""
    return MetricsModel(**metrics.__dict__)
