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
