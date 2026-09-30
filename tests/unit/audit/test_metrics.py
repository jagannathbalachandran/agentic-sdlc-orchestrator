"""Tests for orchestrator.audit.metrics (T8.2, C13-AC1): metrics computed
from a scripted, hash-chained events.jsonl — never from graph.json/run.json.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from orchestrator.audit.event_log import EventLog
from orchestrator.audit.metrics import compute_metrics, metrics_to_model
from orchestrator.models.events import Event, EventDraft, EventType

RUN_ID = "scenario-20260101-001"
T0 = datetime(2026, 1, 1, tzinfo=UTC)


def _at(seconds: int) -> datetime:
    return T0 + timedelta(seconds=seconds)


def _build_events(tmp_path: Path) -> list[Event]:
    """S1 passes first try; S2 fails then passes on retry (RETRY event in
    between); a Change-control approval blocks for 60s; S3 passes first
    try; the run completes.
    """
    log = EventLog(tmp_path / "events.jsonl")

    def append(
        event_type: EventType,
        seconds: int,
        stage: str | None = None,
        attempt: int | None = None,
        payload: dict[str, object] | None = None,
    ) -> None:
        log.append(
            EventDraft(
                run_id=RUN_ID,
                event_type=event_type,
                recorded_at=_at(seconds),
                stage=stage,
                attempt=attempt,
                payload=payload or {},
            )
        )

    append(EventType.STAGE_STARTED, 0, "s1", 1)
    append(EventType.STAGE_FINISHED, 10, "s1", 1, {"status": "passed"})

    append(EventType.STAGE_STARTED, 10, "s2", 1)
    append(EventType.STAGE_FINISHED, 20, "s2", 1, {"status": "failed"})
    append(EventType.RETRY, 20, "s2", 1, {"reason": "invalid output"})
    append(EventType.STAGE_STARTED, 25, "s2", 2)
    append(EventType.STAGE_FINISHED, 40, "s2", 2, {"status": "passed"})

    append(EventType.APPROVAL_REQUESTED, 40, "s6", payload={"checkpoint": "cc"})
    append(EventType.APPROVAL_RECORDED, 100)

    append(EventType.STAGE_STARTED, 100, "s3", 1)
    append(EventType.STAGE_FINISHED, 110, "s3", 1, {"status": "passed"})

    append(EventType.RUN_TERMINAL, 110, payload={"terminal_state": "completed"})

    return log.read_all()


def test_compute_metrics_from_a_failure_retry_success_sequence(
    tmp_path: Path,
) -> None:
    metrics = compute_metrics(_build_events(tmp_path))

    assert metrics.run_success is True
    assert metrics.stage_first_pass_rate == 2 / 3
    assert metrics.retry_count == 1
    assert metrics.rollback_count == 0
    assert metrics.mttr_seconds == 20.0
    assert metrics.end_to_end_latency_seconds == 110.0
    assert metrics.human_wait_seconds == 60.0
    assert metrics.end_to_end_latency_excluding_human_wait_seconds == 50.0
    assert metrics.stage_latency_seconds == {"s1": 10.0, "s2": 25.0, "s3": 10.0}
    assert metrics.agent_call_latency_seconds == {
        "s1:1": 10.0,
        "s2:1": 10.0,
        "s2:2": 15.0,
        "s3:1": 10.0,
    }


def test_compute_metrics_on_no_events_is_all_unknown() -> None:
    metrics = compute_metrics([])

    assert metrics.run_success is None
    assert metrics.stage_first_pass_rate is None
    assert metrics.retry_count == 0
    assert metrics.rollback_count == 0
    assert metrics.mttr_seconds is None
    assert metrics.end_to_end_latency_seconds is None
    assert metrics.human_wait_seconds == 0.0
    assert metrics.end_to_end_latency_excluding_human_wait_seconds is None
    assert metrics.stage_latency_seconds == {}
    assert metrics.agent_call_latency_seconds == {}


def test_compute_metrics_reports_failure_via_stop_event(tmp_path: Path) -> None:
    log = EventLog(tmp_path / "events.jsonl")
    log.append(
        EventDraft(
            run_id=RUN_ID,
            event_type=EventType.STAGE_STARTED,
            recorded_at=_at(0),
            stage="s1",
            attempt=1,
        )
    )
    log.append(
        EventDraft(
            run_id=RUN_ID,
            event_type=EventType.STOP,
            recorded_at=_at(5),
            payload={"reason": "exhausted retries", "attempts": 2},
        )
    )
    metrics = compute_metrics(log.read_all())
    assert metrics.run_success is False


def test_metrics_to_model_round_trips_into_a_pydantic_model(tmp_path: Path) -> None:
    metrics = compute_metrics(_build_events(tmp_path))
    model = metrics_to_model(metrics)
    assert model.run_success is True
    assert model.stage_latency_seconds == metrics.stage_latency_seconds
    # atomic_write_json (audit/run_record.py) needs a BaseModel, not a dataclass.
    assert "run_success" in model.model_dump_json()


def test_compute_metrics_excludes_a_skipped_stage_from_first_pass_rate(
    tmp_path: Path,
) -> None:
    """T9.7/item 8: found on a real run's own metrics.json -- S2 skipped
    (greenfield) plus S0/S1/S3 all passing first try showed up as
    stage_first_pass_rate 0.5 (2/4), not 1.0 (3/3): a "skipped" status
    was being counted as a first-attempt failure instead of being excluded
    from the rate the same way an unfinished span already is."""
    log = EventLog(tmp_path / "events.jsonl")

    def append(
        event_type: EventType,
        seconds: int,
        stage: str | None = None,
        attempt: int | None = None,
        payload: dict[str, object] | None = None,
    ) -> None:
        log.append(
            EventDraft(
                run_id=RUN_ID,
                event_type=event_type,
                recorded_at=_at(seconds),
                stage=stage,
                attempt=attempt,
                payload=payload or {},
            )
        )

    append(EventType.STAGE_STARTED, 0, "s0", 1)
    append(EventType.STAGE_FINISHED, 5, "s0", 1, {"status": "passed"})
    append(EventType.STAGE_STARTED, 5, "s1", 1)
    append(EventType.STAGE_FINISHED, 10, "s1", 1, {"status": "passed"})
    append(EventType.STAGE_STARTED, 10, "s2", 1)
    append(EventType.STAGE_FINISHED, 10, "s2", 1, {"status": "skipped"})
    append(EventType.STAGE_STARTED, 10, "s3", 1)
    append(EventType.STAGE_FINISHED, 20, "s3", 1, {"status": "passed"})

    metrics = compute_metrics(log.read_all())

    assert metrics.stage_first_pass_rate == 1.0


def test_compute_metrics_counts_rollback_events(tmp_path: Path) -> None:
    log = EventLog(tmp_path / "events.jsonl")
    log.append(
        EventDraft(
            run_id=RUN_ID,
            event_type=EventType.ROLLBACK,
            recorded_at=_at(0),
            payload={"to_commit": "abc123"},
        )
    )
    metrics = compute_metrics(log.read_all())
    assert metrics.rollback_count == 1
