"""Hash-chained event log: events.jsonl (requirements.md C12, D-7).

A single EventLog instance must be shared, and its calls serialized, across any
threads writing to the same run's log (architecture-proposal.md §3.2.2) — the
internal lock here is what that serialization point actually is.
"""

from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path

from orchestrator.models.events import Event, EventDraft

GENESIS_HASH = "0" * 64


def _canonical_json(draft: EventDraft, prev_hash: str) -> str:
    return json.dumps(
        {
            "run_id": draft.run_id,
            "stage": draft.stage,
            "attempt": draft.attempt,
            "agent_call_id": draft.agent_call_id,
            "event_type": draft.event_type.value,
            "payload": draft.payload,
            "injected": draft.injected,
            "recorded_at": draft.recorded_at.isoformat(),
            "prev_hash": prev_hash,
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def _compute_hash(draft: EventDraft, sequence: int, prev_hash: str) -> str:
    canonical = json.dumps(
        {"sequence": sequence, **json.loads(_canonical_json(draft, prev_hash))}
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class EventLog:
    """Append-only, hash-chained events.jsonl for one run."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()
        last_sequence, last_hash = self._read_tail()
        self._next_sequence = last_sequence + 1
        self._last_hash = last_hash

    def _read_tail(self) -> tuple[int, str]:
        if not self._path.exists():
            return 0, GENESIS_HASH
        last_line = ""
        with self._path.open(encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    last_line = line
        if not last_line:
            return 0, GENESIS_HASH
        record = json.loads(last_line)
        sequence: int = record["sequence"]
        last_hash: str = record["hash"]
        return sequence, last_hash

    def append(self, draft: EventDraft) -> Event:
        """Append one event, computing its position in the hash chain."""
        with self._lock:
            sequence = self._next_sequence
            prev_hash = self._last_hash
            event_hash = _compute_hash(draft, sequence, prev_hash)
            event = Event(
                **draft.model_dump(),
                sequence=sequence,
                prev_hash=prev_hash,
                hash=event_hash,
            )
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8") as handle:
                handle.write(event.model_dump_json() + "\n")
            self._next_sequence = sequence + 1
            self._last_hash = event_hash
            return event

    def verify(self) -> bool:
        """Recompute the whole chain; False on any tamper, gap, or deletion."""
        if not self._path.exists():
            return True
        expected_prev_hash = GENESIS_HASH
        expected_sequence = 1
        with self._path.open(encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                event = Event.model_validate_json(line)
                if (
                    event.sequence != expected_sequence
                    or event.prev_hash != expected_prev_hash
                ):
                    return False
                draft = EventDraft(
                    **event.model_dump(exclude={"sequence", "prev_hash", "hash"})
                )
                if _compute_hash(draft, event.sequence, event.prev_hash) != event.hash:
                    return False
                expected_prev_hash = event.hash
                expected_sequence += 1
        return True
