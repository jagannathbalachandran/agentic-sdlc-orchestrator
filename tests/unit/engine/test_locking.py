"""Tests for orchestrator.engine.locking."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from orchestrator.audit.run_record import atomic_write_json
from orchestrator.engine.locking import (
    LockRecord,
    acquire_lock,
    pid_is_alive,
    release_lock,
)
from orchestrator.exceptions import ProjectLockedError


def test_acquire_lock_then_release_allows_a_second_acquire(tmp_path: Path) -> None:
    acquire_lock(tmp_path, "demo", "run-1", max_run_duration_seconds=3600)
    release_lock(tmp_path, "demo")
    acquire_lock(tmp_path, "demo", "run-2", max_run_duration_seconds=3600)


def test_acquire_lock_raises_when_held_by_a_live_process(tmp_path: Path) -> None:
    acquire_lock(tmp_path, "demo", "run-1", max_run_duration_seconds=3600)
    with pytest.raises(ProjectLockedError):
        acquire_lock(tmp_path, "demo", "run-2", max_run_duration_seconds=3600)


def test_acquire_lock_reclaims_a_lock_past_max_run_duration(tmp_path: Path) -> None:
    acquire_lock(
        tmp_path, "demo", "run-1", max_run_duration_seconds=60, now=1_000_000.0
    )
    acquire_lock(
        tmp_path, "demo", "run-2", max_run_duration_seconds=60, now=1_000_200.0
    )


def test_acquire_lock_reclaims_a_lock_held_by_a_dead_pid(tmp_path: Path) -> None:
    dead_pid = 999_999
    atomic_write_json(
        tmp_path / "locks" / "demo.lock",
        LockRecord(pid=dead_pid, acquired_at=0.0, run_id="stale-run"),
    )
    acquire_lock(tmp_path, "demo", "run-2", max_run_duration_seconds=3600)


def test_pid_is_alive_is_true_for_the_current_process() -> None:
    assert pid_is_alive(os.getpid()) is True


def test_pid_is_alive_is_false_for_pid_zero_or_negative() -> None:
    assert pid_is_alive(0) is False
    assert pid_is_alive(-1) is False


def test_release_lock_is_idempotent(tmp_path: Path) -> None:
    release_lock(tmp_path, "never-locked")
