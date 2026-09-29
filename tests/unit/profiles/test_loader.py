"""Tests for orchestrator.profiles.loader."""

from __future__ import annotations

from pathlib import Path

import pytest

from orchestrator.exceptions import ConfigValidationError
from orchestrator.profiles.loader import load_profile

VALID_PROFILE_TOML = """
name = "analyst"
persona = "You are a terse requirements analyst."
responsibilities = "Derive FRs with acceptance criteria."
output_contract = "Reply with {summary, produced_ids, files_written}."
"""


def test_load_profile_accepts_valid_toml(tmp_path: Path) -> None:
    path = tmp_path / "analyst.toml"
    path.write_text(VALID_PROFILE_TOML, encoding="utf-8")

    loaded = load_profile(path)

    assert loaded.profile.name == "analyst"
    assert len(loaded.version_hash) == 64


def test_load_profile_hash_changes_when_content_changes(tmp_path: Path) -> None:
    path = tmp_path / "analyst.toml"
    path.write_text(VALID_PROFILE_TOML, encoding="utf-8")
    first = load_profile(path)

    path.write_text(VALID_PROFILE_TOML + '\nrules = ["be terse"]\n', encoding="utf-8")
    second = load_profile(path)

    assert first.version_hash != second.version_hash


def test_load_profile_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ConfigValidationError):
        load_profile(tmp_path / "does-not-exist.toml")


def test_load_profile_rejects_malformed_toml(tmp_path: Path) -> None:
    path = tmp_path / "broken.toml"
    path.write_text("this is not [valid toml", encoding="utf-8")
    with pytest.raises(ConfigValidationError):
        load_profile(path)


def test_load_profile_rejects_missing_required_field(tmp_path: Path) -> None:
    path = tmp_path / "incomplete.toml"
    path.write_text('name = "analyst"\n', encoding="utf-8")
    with pytest.raises(ConfigValidationError):
        load_profile(path)
