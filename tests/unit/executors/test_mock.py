"""Tests for orchestrator.executors.mock."""

from __future__ import annotations

import json
from pathlib import Path

from orchestrator.executors.mock import GENERIC_FALLBACK_SCENARIO_ID, MockExecutor
from orchestrator.models.agent_io import AgentCallOutcome, AgentCallRequest

REPO_ROOT = Path(__file__).resolve().parents[3]
COMMITTED_FIXTURES_ROOT = REPO_ROOT / "fixtures" / "mock"


def _request(
    workspace: Path, scenario_id: str, stage: str, attempt: int = 1
) -> AgentCallRequest:
    return AgentCallRequest(
        profile_name="analyst",
        scenario_id=scenario_id,
        stage=stage,
        attempt=attempt,
        rendered_prompt="irrelevant for the mock executor",
        workspace_path=str(workspace),
        timeout_seconds=600,
        budget_usd=0.5,
    )


def _write_fixture(
    fixtures_root: Path, scenario_id: str, filename: str, content: dict[str, object]
) -> None:
    scenario_dir = fixtures_root / scenario_id
    scenario_dir.mkdir(parents=True, exist_ok=True)
    (scenario_dir / filename).write_text(json.dumps(content), encoding="utf-8")


def test_execute_replays_a_scenario_specific_fixture_and_materializes_its_files(
    tmp_path: Path,
) -> None:
    fixtures_root = tmp_path / "fixtures"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _write_fixture(
        fixtures_root,
        "demo-scenario",
        "S1.json",
        {
            "summary": "derived FR-8",
            "produced_ids": ["FR-8"],
            "files_written": ["01-requirements.md"],
            "files": {"01-requirements.md": "# FR-8\n"},
        },
    )

    executor = MockExecutor(fixtures_root)
    response = executor.execute(_request(workspace, "demo-scenario", "S1"))

    assert response.outcome is AgentCallOutcome.SUCCESS
    assert response.produced_ids == ("FR-8",)
    assert response.files_written == ("01-requirements.md",)
    assert (workspace / "01-requirements.md").read_text(encoding="utf-8") == "# FR-8\n"


def test_execute_falls_back_to_the_generic_fixture_when_scenario_has_none(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    executor = MockExecutor(COMMITTED_FIXTURES_ROOT)

    response = executor.execute(
        _request(workspace, "a-scenario-with-no-fixtures", "S1")
    )

    assert response.outcome is AgentCallOutcome.SUCCESS
    assert response.produced_ids == ("FR-1",)
    assert (workspace / "01-requirements.md").is_file()


def test_execute_returns_error_when_neither_scenario_nor_generic_fixture_exists(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    executor = MockExecutor(COMMITTED_FIXTURES_ROOT)

    response = executor.execute(
        _request(workspace, "a-scenario-with-no-fixtures", "S99")
    )

    assert response.outcome is AgentCallOutcome.ERROR
    assert "no fixture" in response.summary


def test_execute_looks_up_the_attempt_suffixed_fixture_for_attempt_two(
    tmp_path: Path,
) -> None:
    fixtures_root = tmp_path / "fixtures"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _write_fixture(
        fixtures_root,
        "demo-scenario",
        "S6-2.json",
        {
            "summary": "fix applied",
            "produced_ids": [],
            "files_written": [],
            "files": {},
        },
    )

    executor = MockExecutor(fixtures_root)
    response = executor.execute(_request(workspace, "demo-scenario", "S6", attempt=2))

    assert response.outcome is AgentCallOutcome.SUCCESS
    assert response.summary == "fix applied"


def test_bare_name_fixture_is_a_fallback_for_any_attempt_not_only_the_first(
    tmp_path: Path,
) -> None:
    """A re-run (T7.2 design-rejection, T7.4 Clarification-answer) preserves
    its own attempt count rather than resetting to 1 — most scenarios don't
    provide attempt-specific content for that later attempt, so the bare
    `{stage}.json` must still resolve regardless of the attempt number."""
    fixtures_root = tmp_path / "fixtures"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _write_fixture(
        fixtures_root,
        "demo-scenario",
        "S3.json",
        {
            "summary": "designed",
            "produced_ids": ["DD-1"],
            "files_written": ["02-design.md"],
            "files": {},
        },
    )

    executor = MockExecutor(fixtures_root)
    response = executor.execute(_request(workspace, "demo-scenario", "S3", attempt=2))

    assert response.outcome is AgentCallOutcome.SUCCESS
    assert response.produced_ids == ("DD-1",)


def test_generic_fallback_scenario_id_constant_matches_the_fixtures_directory() -> None:
    assert (COMMITTED_FIXTURES_ROOT / GENERIC_FALLBACK_SCENARIO_ID).is_dir()
