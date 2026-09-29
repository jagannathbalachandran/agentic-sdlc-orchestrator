"""Protected paths policy (requirements.md C6, architecture-proposal.md G-4/G-5):
`.github/`, `scripts/check.py`, quality config, `.orchestrator/`, `00-source.md`,
secrets files.

G-4/G-5's resolution: "quality config" means specific `pyproject.toml` TOML
tables (`[tool.ruff]`, `[tool.mypy]`, `[tool.pytest.ini_options]`,
`[tool.coverage.*]`, `[build-system]`), not the whole file — dependency
control (descoped this slice) needs to add approved packages to
`[project.dependencies]` in that same file, so file-level protection would
block a legitimate edit. Section-aware diffing: only those tables are
protected, checked by comparing their content at the run's base commit vs.
HEAD, not by path alone. "secrets files" = `.env*` except `.env.example`, plus
common credential filenames — those stay whole-file-glob protected, alongside
`.github/**`, `scripts/check.py`, `.orchestrator/**`, and every prior REQ's
`00-source.md` baseline (`docs/requirements/*/00-source.md`, not just the
current run's).

Tampering with CI/quality gates or committing to a secrets-file path is
treated as critical (same severity class as main-protection/secret-scan) --
not explicitly stated as an outcome in C6's bullet list, so this is a
documented judgment call, not a literal requirement.
"""

from __future__ import annotations

from fnmatch import fnmatch

from orchestrator.policies.base import PolicyOutcome, PolicyResult, WorkspaceDiff
from orchestrator.workspace.git_ops import read_file_at_commit

POLICY_ID = "protected_paths"
DEFAULT_PROTECTED_TOML_PATH = "pyproject.toml"
DEFAULT_PROTECTED_TOML_TABLE_PREFIXES = (
    "[tool.ruff]",
    "[tool.mypy]",
    "[tool.pytest.ini_options]",
    "[tool.coverage.",
    "[build-system]",
)
DEFAULT_EXEMPT_PATHS = (".env.example",)


def _extract_protected_sections(content: str | None, prefixes: tuple[str, ...]) -> str:
    """Every TOML table block whose header starts with one of `prefixes`,
    concatenated in file order — a simple, format-preserving text comparison
    target, not a semantic TOML diff.
    """
    if content is None:
        return ""
    lines = content.splitlines()
    blocks: list[str] = []
    index = 0
    while index < len(lines):
        if not any(lines[index].strip().startswith(prefix) for prefix in prefixes):
            index += 1
            continue
        block = [lines[index]]
        index += 1
        while index < len(lines) and not lines[index].strip().startswith("["):
            block.append(lines[index])
            index += 1
        blocks.append("\n".join(block))
    return "\n".join(blocks)


class ProtectedPathsPolicy:
    """Flags whole-file protected-path hits, plus quality-config table edits."""

    policy_id = POLICY_ID

    def __init__(
        self,
        protected_path_globs: tuple[str, ...],
        protected_toml_path: str = DEFAULT_PROTECTED_TOML_PATH,
        protected_toml_table_prefixes: tuple[
            str, ...
        ] = DEFAULT_PROTECTED_TOML_TABLE_PREFIXES,
        exempt_paths: tuple[str, ...] = DEFAULT_EXEMPT_PATHS,
    ) -> None:
        self._protected_path_globs = protected_path_globs
        self._protected_toml_path = protected_toml_path
        self._protected_toml_table_prefixes = protected_toml_table_prefixes
        self._exempt_paths = exempt_paths

    def check(self, diff: WorkspaceDiff) -> PolicyResult:
        violations = list(self._whole_file_violations(diff))
        violations.extend(self._toml_section_violations(diff))
        if not violations:
            return PolicyResult(
                policy_id=self.policy_id, passed=True, outcome=PolicyOutcome.OK
            )
        return PolicyResult(
            policy_id=self.policy_id,
            passed=False,
            outcome=PolicyOutcome.CRITICAL,
            violations=tuple(violations),
        )

    def _whole_file_violations(self, diff: WorkspaceDiff) -> list[str]:
        return [
            path
            for path in diff.changed_paths
            if path not in self._exempt_paths
            and any(fnmatch(path, glob) for glob in self._protected_path_globs)
        ]

    def _toml_section_violations(self, diff: WorkspaceDiff) -> list[str]:
        if self._protected_toml_path not in diff.changed_paths:
            return []
        before = read_file_at_commit(
            diff.workspace_path, diff.base_commit, self._protected_toml_path
        )
        after = read_file_at_commit(
            diff.workspace_path, diff.head_commit, self._protected_toml_path
        )
        prefixes = self._protected_toml_table_prefixes
        if _extract_protected_sections(before, prefixes) == _extract_protected_sections(
            after, prefixes
        ):
            return []
        return [
            f"{self._protected_toml_path}: a protected quality-config table changed"
        ]
