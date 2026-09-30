"""Tests for orchestrator.audit.event_log."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from orchestrator.audit.event_log import EventLog, read_events
from orchestrator.models.events import EventDraft, EventType


def _draft(event_type: EventType, **overrides: object) -> EventDraft:
    base: dict[str, object] = {
        "run_id": "run-1",
        "event_type": event_type,
        "recorded_at": datetime(2026, 9, 29, 12, 0, 0, tzinfo=UTC),
    }
    base.update(overrides)
    return EventDraft(**base)  # type: ignore[arg-type]


def test_append_chains_prev_hash_to_the_previous_events_hash(tmp_path: Path) -> None:
    log = EventLog(tmp_path / "events.jsonl")
    first = log.append(_draft(EventType.STAGE_STARTED))
    second = log.append(_draft(EventType.STAGE_FINISHED))
    assert second.prev_hash == first.hash
    assert second.sequence == first.sequence + 1


def test_verify_passes_for_an_untouched_log(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    log = EventLog(path)
    log.append(_draft(EventType.STAGE_STARTED))
    log.append(_draft(EventType.STAGE_FINISHED))
    assert EventLog(path).verify() is True


def test_verify_detects_a_tampered_event(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    log = EventLog(path)
    log.append(_draft(EventType.STAGE_STARTED))
    log.append(_draft(EventType.STAGE_FINISHED))

    lines = path.read_text(encoding="utf-8").splitlines()
    tampered = json.loads(lines[0])
    tampered["stage"] = "S99"
    lines[0] = json.dumps(tampered)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    assert EventLog(path).verify() is False


def test_verify_detects_a_deleted_event(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    log = EventLog(path)
    log.append(_draft(EventType.STAGE_STARTED))
    log.append(_draft(EventType.STAGE_FINISHED))
    log.append(_draft(EventType.GATE_RESULT))

    lines = path.read_text(encoding="utf-8").splitlines()
    del lines[1]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    assert EventLog(path).verify() is False


def test_verify_returns_true_for_a_log_file_that_does_not_exist_yet(
    tmp_path: Path,
) -> None:
    assert EventLog(tmp_path / "events.jsonl").verify() is True


def test_a_pre_existing_empty_log_file_starts_fresh(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    path.write_text("", encoding="utf-8")
    first = EventLog(path).append(_draft(EventType.STAGE_STARTED))
    assert first.sequence == 1
    assert first.prev_hash == "0" * 64


def test_verify_skips_blank_lines_in_the_log_file(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    log = EventLog(path)
    log.append(_draft(EventType.STAGE_STARTED))
    log.append(_draft(EventType.STAGE_FINISHED))

    with path.open("a", encoding="utf-8") as handle:
        handle.write("\n")

    assert EventLog(path).verify() is True


def test_read_all_returns_every_appended_event_in_order(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    log = EventLog(path)
    log.append(_draft(EventType.STAGE_STARTED))
    log.append(_draft(EventType.STAGE_FINISHED))

    events = log.read_all()
    assert [e.event_type for e in events] == [
        EventType.STAGE_STARTED,
        EventType.STAGE_FINISHED,
    ]
    assert [e.sequence for e in events] == [1, 2]


def test_read_events_on_a_missing_file_returns_an_empty_list(tmp_path: Path) -> None:
    assert read_events(tmp_path / "events.jsonl") == []


def test_injected_fault_event_is_recorded_and_a_reloaded_log_continues_the_sequence(
    tmp_path: Path,
) -> None:
    path = tmp_path / "events.jsonl"
    first = EventLog(path).append(
        _draft(EventType.FAULT_INJECTED, stage="S6", injected=True)
    )
    assert first.injected is True

    reloaded = EventLog(path)
    assert reloaded.verify() is True
    next_event = reloaded.append(_draft(EventType.STAGE_FINISHED))
    assert next_event.sequence == 2
    assert next_event.injected is False
