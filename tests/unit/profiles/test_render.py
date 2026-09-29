"""Tests for orchestrator.profiles.render."""

from __future__ import annotations

from orchestrator.models.profile import AgentProfile
from orchestrator.profiles.render import (
    render_allowed_tools_flag,
    render_system_prompt,
    render_tools_flag,
)


def _profile(**overrides: object) -> AgentProfile:
    base: dict[str, object] = {
        "name": "analyst",
        "persona": "You are a terse requirements analyst.",
        "responsibilities": "Derive FRs with acceptance criteria.",
        "output_contract": "Reply with {summary, produced_ids, files_written}.",
    }
    base.update(overrides)
    return AgentProfile(**base)  # type: ignore[arg-type]


def test_render_system_prompt_includes_persona_responsibilities_and_contract() -> None:
    prompt = render_system_prompt(_profile())
    assert "terse requirements analyst" in prompt
    assert "Derive FRs" in prompt
    assert "produced_ids" in prompt


def test_render_system_prompt_includes_rules_when_present() -> None:
    prompt = render_system_prompt(_profile(rules=("never touch main",)))
    assert "Rules:" in prompt
    assert "- never touch main" in prompt


def test_render_system_prompt_omits_rules_section_when_absent() -> None:
    prompt = render_system_prompt(_profile())
    assert "Rules:" not in prompt


def test_render_tools_flag_is_none_when_no_extra_tools_enabled() -> None:
    assert render_tools_flag(_profile()) is None


def test_render_tools_flag_includes_defaults_plus_enabled_tools() -> None:
    flag = render_tools_flag(_profile(enabled_tools=("Bash",)))
    assert flag == "Write,Edit,Read,Bash"


def test_render_allowed_tools_flag_joins_patterns_with_spaces() -> None:
    flag = render_allowed_tools_flag(
        _profile(
            allowed_tool_patterns=("Write", "Edit", "Read", "Bash(python -m pytest *)")
        )
    )
    assert flag == "Write Edit Read Bash(python -m pytest *)"
