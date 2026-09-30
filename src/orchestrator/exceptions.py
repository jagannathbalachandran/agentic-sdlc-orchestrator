"""Domain exceptions. Specific, never swallowed (CLAUDE.md)."""

from __future__ import annotations


class OrchestratorError(Exception):
    """Base class for every orchestrator domain exception."""


class ConfigValidationError(OrchestratorError):
    """A config file failed schema validation (requirements.md C1-AC1)."""

    def __init__(self, path: str, errors: str) -> None:
        super().__init__(f"{path}: {errors}")
        self.path = path
        self.errors = errors


class ProjectNotRegisteredError(OrchestratorError):
    """A run was attempted for a project that isn't registered (C2-AC3)."""

    def __init__(self, project_name: str) -> None:
        super().__init__(f"project not registered: {project_name}")
        self.project_name = project_name


class RunRecordError(OrchestratorError):
    """A run-record file (run.json, graph.json, ...) could not be read or written."""

    def __init__(self, path: str, reason: str) -> None:
        super().__init__(f"{path}: {reason}")
        self.path = path
        self.reason = reason


class GitCommandError(OrchestratorError):
    """A git subprocess call failed."""

    def __init__(self, args: tuple[str, ...], returncode: int, stderr: str) -> None:
        super().__init__(f"git {' '.join(args)} failed ({returncode}): {stderr}")
        self.args_ = args
        self.returncode = returncode
        self.stderr = stderr


class ProjectLockedError(OrchestratorError):
    """Another run already holds this project's lock (D-18: one active run per project)."""

    def __init__(self, project_name: str, holder_pid: int) -> None:
        super().__init__(f"project {project_name!r} is locked by pid {holder_pid}")
        self.project_name = project_name
        self.holder_pid = holder_pid


class NoPendingApprovalError(OrchestratorError):
    """approve/reject/answer was called but the run has no pending checkpoint."""

    def __init__(self, run_id: str) -> None:
        super().__init__(f"run {run_id!r} has no pending approval checkpoint")
        self.run_id = run_id


class RunAlreadyTerminalError(OrchestratorError):
    """The run has already reached a terminal state (completed/failed/rejected/stopped)."""

    def __init__(self, run_id: str, terminal_state: str) -> None:
        super().__init__(f"run {run_id!r} is already {terminal_state}")
        self.run_id = run_id
        self.terminal_state = terminal_state


class NoCheckpointRecordedError(OrchestratorError):
    """rollback was called before any stage's exit gate has ever passed (G-14)."""

    def __init__(self, run_id: str) -> None:
        super().__init__(f"run {run_id!r} has no recorded checkpoint to roll back to")
        self.run_id = run_id
