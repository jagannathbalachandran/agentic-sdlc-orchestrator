"""Render an AgentProfile into claude -p CLI inputs (O-10).

Rendered prompt + flags, not Claude Code subagent/skill files — keeps the
executor interface free of Claude-Code-specific filesystem side effects
(architecture-proposal.md O-10).
"""

from __future__ import annotations

from orchestrator.models.profile import DEFAULT_ALLOWED_TOOL_PATTERNS, AgentProfile


def render_system_prompt(profile: AgentProfile) -> str:
    """Build the --append-system-prompt text from persona/responsibilities/rules."""
    lines = [profile.persona, "", profile.responsibilities]
    if profile.rules:
        lines.extend(["", "Rules:", *(f"- {rule}" for rule in profile.rules)])
    lines.extend(["", profile.output_contract])
    return "\n".join(lines)


def render_tools_flag(profile: AgentProfile) -> str | None:
    """--tools value: only needed when re-enabling something --restricted removed.

    None means "don't pass --tools at all" — the profile needs nothing beyond
    --restricted's own defaults (Write/Edit/Read).
    """
    if not profile.enabled_tools:
        return None
    return ",".join((*DEFAULT_ALLOWED_TOOL_PATTERNS, *profile.enabled_tools))


def render_allowed_tools_flag(profile: AgentProfile) -> str:
    """--allowedTools value: fine-grained auto-approval patterns."""
    return " ".join(profile.allowed_tool_patterns)
