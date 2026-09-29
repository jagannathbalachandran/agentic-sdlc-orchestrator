"""Tests for the 7 authored role profiles under agents/profiles/*.toml (T4.2, C8).

Validates each against the AgentProfile schema and checks the Bash-scoping rule:
only developer/test_engineer get a Bash(python -m pytest *)-scoped allowlist entry;
every other role gets no Bash entry at all (ADR-001).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from orchestrator.profiles.loader import load_profile

PROFILES_ROOT = Path(__file__).resolve().parents[3] / "agents" / "profiles"

ROLES_WITH_SCOPED_BASH = {"developer", "test_engineer"}
ALL_ROLES = {
    "analyst",
    "architect",
    "planner",
    "developer",
    "test_engineer",
    "technical_writer",
    "reviewer",
}
BASH_PYTEST_PATTERN = "Bash(python -m pytest *)"


def _profile_paths() -> list[Path]:
    return sorted(PROFILES_ROOT.glob("*.toml"))


def test_agents_profiles_directory_has_exactly_the_seven_expected_roles() -> None:
    names = {path.stem for path in _profile_paths()}
    assert names == ALL_ROLES


@pytest.mark.parametrize("path", _profile_paths(), ids=lambda p: p.stem)
def test_each_profile_validates_against_the_agent_profile_schema(path: Path) -> None:
    loaded = load_profile(path)
    assert loaded.profile.name == path.stem
    assert loaded.profile.persona
    assert loaded.profile.responsibilities
    assert loaded.profile.output_contract
    assert len(loaded.version_hash) == 64


@pytest.mark.parametrize("role", sorted(ROLES_WITH_SCOPED_BASH))
def test_developer_and_test_engineer_get_the_scoped_pytest_bash_pattern(
    role: str,
) -> None:
    loaded = load_profile(PROFILES_ROOT / f"{role}.toml")
    assert "Bash" in loaded.profile.enabled_tools
    assert BASH_PYTEST_PATTERN in loaded.profile.allowed_tool_patterns


@pytest.mark.parametrize("role", sorted(ALL_ROLES - ROLES_WITH_SCOPED_BASH))
def test_every_other_role_has_no_bash_entry_at_all(role: str) -> None:
    loaded = load_profile(PROFILES_ROOT / f"{role}.toml")
    assert "Bash" not in loaded.profile.enabled_tools
    assert not any(
        "Bash" in pattern for pattern in loaded.profile.allowed_tool_patterns
    )
