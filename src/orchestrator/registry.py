"""Project registry: name -> repo URL mapping (requirements.md C1 `register`, §8).

`resolve_project` matches `config.validate.ProjectLookup`'s shape (minus
`orch_home`, which the CLI wiring in T2.3 partial-applies) — this is the real,
file-backed implementation that module's injected abstraction was written against.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from orchestrator.audit.run_record import atomic_write_json, read_json
from orchestrator.exceptions import RunRecordError

REGISTRY_FILENAME = "projects.json"


class ProjectRegistry(BaseModel):
    """projects.json: registered project name -> repo URL."""

    projects: dict[str, str] = Field(default_factory=dict)


def _registry_path(orch_home: Path) -> Path:
    return orch_home / REGISTRY_FILENAME


def _load_registry(orch_home: Path) -> ProjectRegistry:
    path = _registry_path(orch_home)
    if not path.is_file():
        return ProjectRegistry()
    try:
        return read_json(path, ProjectRegistry)
    except RunRecordError:
        return ProjectRegistry()


def register_project(orch_home: Path, project_name: str, repo_url: str) -> None:
    """Register (or update) a project name -> repo URL mapping."""
    registry = _load_registry(orch_home)
    registry.projects[project_name] = repo_url
    atomic_write_json(_registry_path(orch_home), registry)


def resolve_project(orch_home: Path, project_name: str) -> str | None:
    """Return the project's repo URL, or None if unregistered."""
    return _load_registry(orch_home).projects.get(project_name)
