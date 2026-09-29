"""Tests for orchestrator.policies.schema_change_control (C6-AC1)."""

from __future__ import annotations

from pathlib import Path

from orchestrator.policies.base import FileChange, WorkspaceDiff
from orchestrator.policies.schema_change_control import SchemaChangeControlPolicy

MIGRATION_GLOBS = (
    "migrations/*",
    "*/migrations/*",
    "alembic/versions/*",
    "*/alembic/versions/*",
)


def _diff(paths: tuple[str, ...]) -> WorkspaceDiff:
    return WorkspaceDiff(
        workspace_path=Path("/workspace"),
        base_commit="base",
        head_commit="head",
        current_branch="run/demo",
        files=tuple(
            FileChange(path=path, added_lines=(), removed_lines=()) for path in paths
        ),
    )


def test_passes_when_no_migration_path_changed() -> None:
    result = SchemaChangeControlPolicy(MIGRATION_GLOBS).check(_diff(("src/app.py",)))
    assert result.passed
    assert result.outcome.value == "ok"


def test_flags_a_root_level_migration_as_change_control() -> None:
    result = SchemaChangeControlPolicy(MIGRATION_GLOBS).check(
        _diff(("migrations/0001_init.py",))
    )
    assert not result.passed
    assert result.outcome.value == "change_control"
    assert result.violations == ("migrations/0001_init.py",)


def test_flags_a_nested_alembic_migration_as_change_control() -> None:
    result = SchemaChangeControlPolicy(MIGRATION_GLOBS).check(
        _diff(("alembic/versions/0001_add_clicks.py",))
    )
    assert not result.passed
    assert result.outcome.value == "change_control"
