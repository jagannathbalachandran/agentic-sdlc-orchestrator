"""Tests for orchestrator.models.events."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from orchestrator.models.events import Event, EventType


def test_event_defaults_injected_to_false_with_empty_payload() -> None:
    event = Event(
        sequence=1,
        run_id="run-1",
        event_type=EventType.STAGE_STARTED,
        recorded_at=datetime(2026, 9, 29, 12, 0, 0, tzinfo=UTC),
        prev_hash="0" * 64,
        hash="1" * 64,
    )
    assert event.injected is False
    assert event.payload == {}


def test_event_can_mark_injected_fault() -> None:
    event = Event(
        sequence=5,
        run_id="run-1",
        stage="S6",
        attempt=1,
        event_type=EventType.FAULT_INJECTED,
        injected=True,
        recorded_at=datetime(2026, 9, 29, 12, 0, 0, tzinfo=UTC),
        prev_hash="1" * 64,
        hash="2" * 64,
    )
    assert event.injected is True


def test_event_requires_sequence_field() -> None:
    with pytest.raises(ValidationError):
        Event(
            run_id="run-1",
            event_type=EventType.STAGE_STARTED,
            recorded_at=datetime(2026, 9, 29, 12, 0, 0, tzinfo=UTC),
            prev_hash="0" * 64,
            hash="1" * 64,
        )  # type: ignore[call-arg]
