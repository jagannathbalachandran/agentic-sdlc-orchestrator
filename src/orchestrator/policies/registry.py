"""Builds the real, configured set of S6 policies (requirements.md C6) from
`config/defaults.toml` and the stage graph's own `allowed_write_paths` — the
CLI commands' one integration point with the policies package, so `drive()`
itself stays config-path-agnostic (its own `policies` param has no default).
"""

from __future__ import annotations

from pathlib import Path

from orchestrator.config.loader import load_defaults_config
from orchestrator.engine.graph import GRAPH
from orchestrator.policies.base import Policy
from orchestrator.policies.diff_size_limit import DiffSizeLimitPolicy
from orchestrator.policies.main_protection import MainProtectionPolicy
from orchestrator.policies.path_partitioning import PathPartitioningPolicy
from orchestrator.policies.protected_paths import ProtectedPathsPolicy
from orchestrator.policies.schema_change_control import SchemaChangeControlPolicy
from orchestrator.policies.secret_scan import SecretScanPolicy
from orchestrator.policies.workspace_confinement import WorkspaceConfinementPolicy

DEFAULTS_CONFIG_PATH = Path("config/defaults.toml")


def _allowed_path_globs_union() -> tuple[str, ...]:
    """Every stage's own `allowed_write_paths`, combined.

    S6 checks the whole run's diff at once — it has no way to attribute a
    changed file back to the specific stage that wrote it (two sibling stages
    can even share one commit, T6.1) — so path-partitioning checks "was this
    file allowed for *some* stage", not per-stage attribution.
    """
    globs: list[str] = []
    for spec in GRAPH.values():
        globs.extend(spec.allowed_write_paths)
    return tuple(globs)


def build_default_policies() -> tuple[Policy, ...]:
    """The real 7 policies (dependency control descoped this slice), configured
    from `config/defaults.toml` (resolved relative to the current working
    directory, matching `cli/commands/_common.py`'s existing convention — the
    orchestrator CLI is always run from its own repo root).
    """
    defaults = load_defaults_config(DEFAULTS_CONFIG_PATH)
    policy_config = defaults.policy
    return (
        WorkspaceConfinementPolicy(),
        PathPartitioningPolicy(_allowed_path_globs_union()),
        ProtectedPathsPolicy(policy_config.protected_path_globs),
        MainProtectionPolicy(),
        SecretScanPolicy(policy_config.secret_scan_patterns),
        SchemaChangeControlPolicy(policy_config.migration_path_globs),
        DiffSizeLimitPolicy(
            max_lines=defaults.limits.diff_size_limit_lines,
            max_files=defaults.limits.diff_size_limit_files,
        ),
    )
