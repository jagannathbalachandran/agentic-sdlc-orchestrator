"""Tests for orchestrator.registry."""

from __future__ import annotations

from pathlib import Path

from orchestrator.registry import register_project, resolve_project


def test_resolve_project_returns_none_for_an_unregistered_project(
    tmp_path: Path,
) -> None:
    assert resolve_project(tmp_path, "demo") is None


def test_register_then_resolve_round_trips(tmp_path: Path) -> None:
    register_project(tmp_path, "demo", "https://example.com/demo.git")
    assert resolve_project(tmp_path, "demo") == "https://example.com/demo.git"


def test_register_project_updates_an_existing_entry(tmp_path: Path) -> None:
    register_project(tmp_path, "demo", "https://example.com/demo-old.git")
    register_project(tmp_path, "demo", "https://example.com/demo-new.git")
    assert resolve_project(tmp_path, "demo") == "https://example.com/demo-new.git"


def test_resolve_project_survives_a_missing_orch_home_directory(tmp_path: Path) -> None:
    assert resolve_project(tmp_path / "does-not-exist-dir", "demo") is None
