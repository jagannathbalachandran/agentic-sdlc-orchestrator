"""Pydantic schemas for the layered config (requirements.md §8, §9).

Phase 1 is global-only: no project/scenario merge-tightening logic (§9 stays COULD).
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from orchestrator.models._patterns import REQ_ID_PATTERN


class Limits(BaseModel):
    """Run-level safety limits (requirements.md C9; defaults per architecture-proposal.md G-6)."""

    max_run_duration_minutes: int = Field(gt=0)
    max_agent_calls: int = Field(gt=0)
    per_call_timeout_seconds: int = Field(gt=0)
    diff_size_limit_lines: int = Field(gt=0)
    diff_size_limit_files: int = Field(gt=0)


class RetryLimits(BaseModel):
    """Bounded-retry attempt counts (requirements.md C9)."""

    invalid_output_max_attempts: int = Field(gt=0)
    s6_failure_max_attempts: int = Field(gt=0)
    s7b_findings_max_attempts: int = Field(gt=0)


class PolicyConfig(BaseModel):
    """Data-shaped policy parameters, evaluated by Python classes (O-7)."""

    protected_path_globs: tuple[str, ...]
    secret_scan_patterns: tuple[str, ...]


class DefaultsConfig(BaseModel):
    """config/defaults.toml: the global stage-graph/gate/policy configuration."""

    coverage_threshold_percent: int = Field(gt=0, le=100)
    limits: Limits
    retry_limits: RetryLimits
    policy: PolicyConfig


class ProjectConfig(BaseModel):
    """.orchestrator/project.toml: the target's approved-dependency list (§9)."""

    project_name: str
    approved_dependencies: tuple[str, ...] = ()


class ScenarioConfig(BaseModel):
    """.orchestrator/scenarios/<scenario>.toml: one scenario's inputs (§3 glossary)."""

    scenario_id: str
    req_id: str = Field(pattern=REQ_ID_PATTERN)
    requirement_text: str
    base_ref: str | None = None
    inject_fault: bool = False
