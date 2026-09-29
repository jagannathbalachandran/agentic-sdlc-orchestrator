"""Agent profile domain model: persona, responsibilities, tool allowlist, output
contract (requirements.md C8; architecture-proposal.md O-10).
"""

from __future__ import annotations

from pydantic import BaseModel

DEFAULT_ALLOWED_TOOL_PATTERNS = ("Write", "Edit", "Read")


class AgentProfile(BaseModel):
    """One role definition, loaded from agents/profiles/<name>.toml (C8)."""

    name: str
    persona: str
    responsibilities: str
    output_contract: str
    rules: tuple[str, ...] = ()
    enabled_tools: tuple[str, ...] = ()
    allowed_tool_patterns: tuple[str, ...] = DEFAULT_ALLOWED_TOOL_PATTERNS
