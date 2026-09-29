"""Per-project run lock: PID + staleness, reclaimable (closes gap G-2).

Acquired at the start of engine.fsm.drive(), released when drive() returns —
never held across a process boundary at a normal pause point (architecture-
proposal.md §3.2.1).
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

from pydantic import BaseModel

from orchestrator.audit.run_record import atomic_write_json, read_json
from orchestrator.exceptions import ProjectLockedError, RunRecordError

LOCKS_SUBDIR = "locks"

if sys.platform == "win32":
    import ctypes

    _PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    _STILL_ACTIVE = 259

    def pid_is_alive(pid: int) -> bool:
        """Best-effort liveness check, portable across the platforms in NFR §13."""
        if pid <= 0:
            return False
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        try:
            exit_code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return False
            return bool(exit_code.value == _STILL_ACTIVE)
        finally:
            kernel32.CloseHandle(handle)
else:

    def pid_is_alive(pid: int) -> bool:
        """Best-effort liveness check, portable across the platforms in NFR §13."""
        if pid <= 0:
            return False
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except OSError:
            return False
        return True


class LockRecord(BaseModel):
    """What's written to <project>.lock."""

    pid: int
    acquired_at: float
    run_id: str


def _lock_path(orch_home: Path, project_name: str) -> Path:
    return orch_home / LOCKS_SUBDIR / f"{project_name}.lock"


def _is_stale(record: LockRecord, max_run_duration_seconds: float, now: float) -> bool:
    if not pid_is_alive(record.pid):
        return True
    return (now - record.acquired_at) > max_run_duration_seconds


def acquire_lock(
    orch_home: Path,
    project_name: str,
    run_id: str,
    max_run_duration_seconds: float,
    now: float | None = None,
) -> None:
    """Acquire the project lock, reclaiming it if the previous holder is stale."""
    current_time = now if now is not None else time.time()
    path = _lock_path(orch_home, project_name)
    if path.is_file():
        existing = _read_existing_lock(path)
        if existing is not None and not _is_stale(
            existing, max_run_duration_seconds, current_time
        ):
            raise ProjectLockedError(project_name, existing.pid)
    atomic_write_json(
        path, LockRecord(pid=os.getpid(), acquired_at=current_time, run_id=run_id)
    )


def _read_existing_lock(path: Path) -> LockRecord | None:
    try:
        return read_json(path, LockRecord)
    except RunRecordError:
        return None


def release_lock(orch_home: Path, project_name: str) -> None:
    """Release the project lock (idempotent: a no-op if it's already gone)."""
    _lock_path(orch_home, project_name).unlink(missing_ok=True)
