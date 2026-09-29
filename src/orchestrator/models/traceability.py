"""Traceability chain models: FR/AC, DD, Task, commit trailers (requirements.md §7.2)."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, Field

from orchestrator.models._patterns import (
    AC_ID_PATTERN,
    DD_ID_PATTERN,
    FR_ID_PATTERN,
    REQ_ID_PATTERN,
    TASK_ID_PATTERN,
)

FrId = Annotated[str, Field(pattern=FR_ID_PATTERN)]
DdId = Annotated[str, Field(pattern=DD_ID_PATTERN)]


class AcceptanceCriterion(BaseModel):
    """One acceptance criterion under a functional requirement."""

    ac_id: str = Field(pattern=AC_ID_PATTERN)
    text: str


class FunctionalRequirement(BaseModel):
    """One FR, citing its REQ, with at least one acceptance criterion (C10-AC1)."""

    fr_id: str = Field(pattern=FR_ID_PATTERN)
    req_id: str = Field(pattern=REQ_ID_PATTERN)
    text: str
    acceptance_criteria: tuple[AcceptanceCriterion, ...] = Field(min_length=1)


class DesignDecision(BaseModel):
    """One DD, citing at least one FR it serves (C10-AC1)."""

    dd_id: str = Field(pattern=DD_ID_PATTERN)
    fr_ids: tuple[FrId, ...] = Field(min_length=1)
    text: str


class Task(BaseModel):
    """One implementation task, citing at least one DD and sitting under an FR."""

    task_id: str = Field(pattern=TASK_ID_PATTERN)
    fr_id: str = Field(pattern=FR_ID_PATTERN)
    dd_ids: tuple[DdId, ...] = Field(min_length=1)
    expected_files: tuple[str, ...] = ()


class CommitTrailers(BaseModel):
    """Git trailers every orchestrator commit carries (requirements.md §7.2).

    Task/FR are omitted for non-task commits (S0, S1, S3, S4, S5b, S7a, Join S7).
    """

    run: str
    stage: str
    req_id: str = Field(pattern=REQ_ID_PATTERN)
    task_id: str | None = Field(default=None, pattern=TASK_ID_PATTERN)
    fr_id: str | None = Field(default=None, pattern=FR_ID_PATTERN)
