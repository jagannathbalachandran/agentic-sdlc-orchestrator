"""Tests for orchestrator.engine.graph."""

from __future__ import annotations

import pytest

from orchestrator.engine.graph import GRAPH, get_stage_spec
from orchestrator.models.graph import StageId


def test_graph_defines_s0_and_s1_with_s1_depending_on_s0() -> None:
    assert StageId.S0_PREPARE in GRAPH
    assert StageId.S1_REQUIREMENTS in GRAPH
    assert GRAPH[StageId.S1_REQUIREMENTS].depends_on == (StageId.S0_PREPARE,)


def test_get_stage_spec_raises_for_a_stage_not_yet_defined() -> None:
    with pytest.raises(KeyError):
        get_stage_spec(StageId.S2_CODEBASE_ANALYSIS)
