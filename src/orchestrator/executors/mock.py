"""Mock executor: fixture replay + generic fallback (O-4 revised, O-8, closes G-8).

Materializes each fixture's file contents into the workspace — gates read files,
not the response (O-4) — so a mock run leaves the same kind of on-disk artifact a
real run would. Fixture lookup is keyed by (scenario_id, stage, attempt); a
scenario with no recorded fixture falls back to a small generic set used by the
orchestrator's own tests.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from orchestrator.models.agent_io import (
    AgentCallOutcome,
    AgentCallRequest,
    AgentCallResponse,
)

GENERIC_FALLBACK_SCENARIO_ID = "_generic"


class MockExecutor:
    """Executor implementation backed by recorded (or generic) JSON fixtures."""

    def __init__(self, fixtures_root: Path) -> None:
        self._fixtures_root = fixtures_root

    def execute(self, request: AgentCallRequest) -> AgentCallResponse:
        """Replay the matching fixture, or the generic fallback, into the workspace."""
        fixture = self._load_fixture(
            request.scenario_id, request.stage, request.attempt
        )
        if fixture is None:
            fixture = self._load_fixture(
                GENERIC_FALLBACK_SCENARIO_ID, request.stage, request.attempt
            )
        if fixture is None:
            return AgentCallResponse(
                outcome=AgentCallOutcome.ERROR,
                summary=(
                    f"no fixture for stage={request.stage} "
                    f"(scenario={request.scenario_id}, generic fallback also missing)"
                ),
                duration_seconds=0.0,
            )
        _materialize_files(fixture, Path(request.workspace_path))
        return AgentCallResponse(
            outcome=AgentCallOutcome.SUCCESS,
            summary=str(fixture.get("summary", "")),
            produced_ids=tuple(fixture.get("produced_ids", ())),
            files_written=tuple(fixture.get("files_written", ())),
            high_severity_findings=tuple(fixture.get("high_severity_findings", ())),
            blocking_questions=tuple(fixture.get("blocking_questions", ())),
            duration_seconds=0.0,
        )

    def _load_fixture(
        self, scenario_id: str, stage: str, attempt: int
    ) -> dict[str, Any] | None:
        for path in self._candidate_paths(scenario_id, stage, attempt):
            if path.is_file():
                data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
                return data
        return None

    def _candidate_paths(
        self, scenario_id: str, stage: str, attempt: int
    ) -> tuple[Path, ...]:
        """The attempt-specific fixture first; the bare `{stage}.json` as a
        fallback regardless of attempt — most tests/scenarios don't need
        attempt-specific content, only the ones that provide it (e.g. a
        bounded-retry test's second attempt) actually get different content.
        """
        scenario_dir = self._fixtures_root / scenario_id
        return (
            scenario_dir / f"{stage}-{attempt}.json",
            scenario_dir / f"{stage}.json",
        )


def _materialize_files(fixture: dict[str, Any], workspace: Path) -> None:
    files = fixture.get("files", {})
    if not isinstance(files, dict):
        return
    for relative_path, content in files.items():
        target = workspace / str(relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(str(content), encoding="utf-8")
