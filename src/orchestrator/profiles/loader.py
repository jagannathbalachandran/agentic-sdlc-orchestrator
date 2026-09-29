"""Load agent profiles from agents/profiles/*.toml (O-10)."""

from __future__ import annotations

import hashlib
import tomllib
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from orchestrator.exceptions import ConfigValidationError
from orchestrator.models.profile import AgentProfile


@dataclass(frozen=True)
class LoadedProfile:
    """A profile plus a content hash, recorded on every call (C8-AC2)."""

    profile: AgentProfile
    version_hash: str


def load_profile(path: Path) -> LoadedProfile:
    """Load and validate one agents/profiles/<name>.toml."""
    if not path.is_file():
        raise ConfigValidationError(str(path), "file not found")
    raw = path.read_bytes()
    try:
        data = tomllib.loads(raw.decode("utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigValidationError(str(path), f"malformed TOML: {exc}") from exc
    try:
        profile = AgentProfile.model_validate(data)
    except ValidationError as exc:
        raise ConfigValidationError(str(path), str(exc)) from exc
    version_hash = hashlib.sha256(raw).hexdigest()
    return LoadedProfile(profile=profile, version_hash=version_hash)
