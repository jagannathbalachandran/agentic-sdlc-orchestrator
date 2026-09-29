"""Tests for orchestrator.models.traceability."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from orchestrator.models.traceability import (
    AcceptanceCriterion,
    CommitTrailers,
    DesignDecision,
    FunctionalRequirement,
    Task,
)


def test_functional_requirement_accepts_valid_input() -> None:
    fr = FunctionalRequirement(
        fr_id="FR-8",
        req_id="REQ-003",
        text="Record click events on redirect.",
        acceptance_criteria=(AcceptanceCriterion(ac_id="FR-8.AC1", text="..."),),
    )
    assert fr.acceptance_criteria[0].ac_id == "FR-8.AC1"


def test_functional_requirement_rejects_empty_acceptance_criteria() -> None:
    with pytest.raises(ValidationError):
        FunctionalRequirement(
            fr_id="FR-8", req_id="REQ-003", text="x", acceptance_criteria=()
        )


def test_functional_requirement_rejects_malformed_fr_id() -> None:
    with pytest.raises(ValidationError):
        FunctionalRequirement(
            fr_id="FR8",
            req_id="REQ-003",
            text="x",
            acceptance_criteria=(AcceptanceCriterion(ac_id="FR-8.AC1", text="y"),),
        )


def test_design_decision_requires_at_least_one_fr() -> None:
    with pytest.raises(ValidationError):
        DesignDecision(dd_id="DD-1", fr_ids=(), text="x")


def test_task_accepts_valid_input_and_defaults_expected_files_to_empty() -> None:
    task = Task(task_id="T-8.2", fr_id="FR-8", dd_ids=("DD-1",))
    assert task.expected_files == ()


def test_task_rejects_malformed_task_id() -> None:
    with pytest.raises(ValidationError):
        Task(task_id="T-8-2", fr_id="FR-8", dd_ids=("DD-1",))


def test_commit_trailers_allows_task_and_fr_to_be_omitted() -> None:
    trailers = CommitTrailers(run="run-1", stage="S1", req_id="REQ-003")
    assert trailers.task_id is None
    assert trailers.fr_id is None


def test_commit_trailers_rejects_malformed_task_id() -> None:
    with pytest.raises(ValidationError):
        CommitTrailers(run="run-1", stage="S5a", req_id="REQ-003", task_id="bad")
