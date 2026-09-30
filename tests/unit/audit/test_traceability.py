"""Tests for orchestrator.audit.traceability (T8.1, C10-AC3/AC5)."""

from __future__ import annotations

from orchestrator.audit.traceability import (
    CommitInfo,
    TraceabilityInputs,
    backward_trace,
    generate_traceability_report,
)

REQUIREMENTS_MD = (
    "# Requirements\n\n## FR-1\nCites: REQ-1\nbody\n\n### FR-1.AC1\nac body\n"
)
DESIGN_MD = "# Design\n\n## DD-1\nCites: FR-1\nbody\n"
PLAN_MD = "# Plan\n\n## FR-1\n- T-1.1 (DD-1): implement the thing.\n"
ACCEPTANCE_TEST_FILES = {
    "tests/acceptance/test_fr1_ac1.py": "# Traces: FR-1.AC1\n\ndef test_it(): ...\n"
}
COMMITS = (CommitInfo(sha="a" * 40, task_id="T-1.1"),)


def _complete_inputs() -> TraceabilityInputs:
    return TraceabilityInputs(
        requirements_md=REQUIREMENTS_MD,
        design_md=DESIGN_MD,
        plan_md=PLAN_MD,
        commits=COMMITS,
        acceptance_test_files=ACCEPTANCE_TEST_FILES,
    )


def test_generate_traceability_report_has_no_gaps_for_a_complete_chain() -> None:
    report = generate_traceability_report(_complete_inputs())
    assert "## Gaps" in report
    assert "None." in report
    assert "FR-1" in report
    assert "FR-1.AC1" in report
    assert "DD-1" in report
    assert "T-1.1" in report
    assert "aaaaaaaa" in report  # the commit sha, truncated to 8 chars
    assert "tests/acceptance/test_fr1_ac1.py" in report


def test_generate_traceability_report_has_no_gaps_with_real_titled_headings() -> None:
    """T9.8 item 3: this module had its own, separate copy of FR_HEADING/
    DD_HEADING/AC_HEADING that never accepted a title after the ID (the same
    class of bug as item 2's citation gates) -- a real run's `## DD-1:
    <title>` design would have produced a traceability.md with every FR
    showing "no DD"/"no AC", even though every citation gate had passed.
    """
    inputs = TraceabilityInputs(
        requirements_md=(
            "# Requirements\n\n## FR-1: Shorten a URL\nCites: REQ-1\nbody\n\n"
            "### FR-1.AC1: 201 on success\nac body\n"
        ),
        design_md="# Design\n\n## DD-1: URL shortening endpoint\nCites: FR-1\nbody\n",
        plan_md=(
            "# Plan\n\n## FR-1: Shorten a URL\n- T-1.1 (DD-1): implement the thing.\n"
        ),
        commits=COMMITS,
        acceptance_test_files=ACCEPTANCE_TEST_FILES,
    )

    report = generate_traceability_report(inputs)

    assert "## Gaps" in report
    assert "None." in report
    assert "FR-1.AC1" in report
    assert "DD-1" in report
    assert "T-1.1" in report


def test_generate_traceability_report_flags_every_missing_link_in_the_chain() -> None:
    inputs = TraceabilityInputs(
        requirements_md="# Requirements\n\n## FR-1\nCites: REQ-1\nbody, no AC\n",
        design_md="# Design\n\nno DDs here\n",
        plan_md="# Plan\n\nno FR sections here\n",
        commits=(),
        acceptance_test_files={},
    )
    report = generate_traceability_report(inputs)
    assert "FR-1: no AC" in report
    assert "FR-1: no DD" in report
    assert "FR-1: no task" in report
    # No task -> "no commit"/"no test" aren't separately reported (nothing to
    # attach a commit or test to yet); the "no task" gap already covers it.


def test_generate_traceability_report_flags_a_task_with_no_commit() -> None:
    inputs = TraceabilityInputs(
        requirements_md=REQUIREMENTS_MD,
        design_md=DESIGN_MD,
        plan_md=PLAN_MD,
        commits=(),  # the task exists, but nothing committed it
        acceptance_test_files=ACCEPTANCE_TEST_FILES,
    )
    report = generate_traceability_report(inputs)
    assert "FR-1: no commit" in report


def test_generate_traceability_report_flags_an_ac_with_no_test() -> None:
    inputs = TraceabilityInputs(
        requirements_md=REQUIREMENTS_MD,
        design_md=DESIGN_MD,
        plan_md=PLAN_MD,
        commits=COMMITS,
        acceptance_test_files={},  # no test tagged FR-1.AC1
    )
    report = generate_traceability_report(inputs)
    assert "FR-1: no test" in report


def test_backward_trace_walks_commit_to_task_to_fr_to_req() -> None:
    trace = backward_trace(_complete_inputs(), commit_sha="a" * 40)
    assert trace.task_id == "T-1.1"
    assert trace.fr_id == "FR-1"
    assert trace.req_id == "REQ-1"


def test_backward_trace_is_all_none_for_an_unknown_commit() -> None:
    trace = backward_trace(_complete_inputs(), commit_sha="unknown-sha")
    assert trace.task_id is None
    assert trace.fr_id is None
    assert trace.req_id is None


def test_backward_trace_is_all_none_for_a_commit_with_no_task_trailer() -> None:
    inputs = TraceabilityInputs(
        requirements_md=REQUIREMENTS_MD,
        design_md=DESIGN_MD,
        plan_md=PLAN_MD,
        commits=(CommitInfo(sha="b" * 40, task_id=None),),
        acceptance_test_files=ACCEPTANCE_TEST_FILES,
    )
    trace = backward_trace(inputs, commit_sha="b" * 40)
    assert trace.task_id is None
    assert trace.fr_id is None
    assert trace.req_id is None
