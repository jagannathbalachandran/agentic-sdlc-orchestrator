"""Tests for orchestrator.engine.plan_tasks (T9.8): the shared parser S4's
PlanCitationGate and S5a's per-task loop both use, so they can never see a
different task count for the same file again."""

from __future__ import annotations

from orchestrator.engine.plan_tasks import parse_fr_to_req, parse_plan_tasks

# Verbatim from a real run: greenfield-minimal-20260930-002's own 03-plan.md,
# which S4's gate passed but S5a then found "no parseable tasks" in (T9.8) --
# the real-titled-heading shape plan_tasks.py's own, separate FR_HEADING
# regex (before this fix) never matched.
REAL_PLAN_MD = """# Plan

## FR-1: Shorten a long URL
- T-1.1 (DD-1): Add the `flask>=3.0,<4.0` runtime dependency to `pyproject.toml` and implement the application factory (`create_app`, `register_routes`) in `src/service/app.py`, binding a `URLStore` to `app.config["URL_STORE"]` with route skeletons for `POST /shorten` and `GET /<code>`. No dependencies.
- T-1.2 (DD-3): Implement short-code generation in `src/service/codes.py` (`CODE_ALPHABET`, `CODE_LENGTH`, `generate_code` using `secrets.choice`). No dependencies.
- T-1.3 (DD-3): Implement `URLStore` (`put`/`get`) in `src/service/storage.py`, calling `codes.generate_code` in a retry loop on collision. Depends on: T-1.2.
- T-1.4 (DD-2): Implement `is_valid_url` in `src/service/urls.py` (str check, http/https scheme, non-empty netloc via `urllib.parse.urlparse`). No dependencies.
- T-1.5 (DD-2): Implement the `POST /shorten` handler in `src/service/app.py` — parse JSON body, validate via `is_valid_url`, delegate to `URLStore.put`, and return the `201`/`400` response contract from DD-2. Depends on: T-1.1, T-1.3, T-1.4.

## FR-2: Redirect from a short code
- T-2.1 (DD-4): Implement the `GET /<code>` handler (`redirect_to_original`) in `src/service/app.py` — look up the code via `URLStore.get`, returning a `302` redirect with `Location` set on hit or aborting with `404` (no `Location` header) on miss. Depends on: T-1.1, T-1.3.
"""


def test_parse_plan_tasks_parses_all_six_tasks_from_the_real_titled_heading_plan() -> (
    None
):
    tasks = parse_plan_tasks(REAL_PLAN_MD)

    assert [task.task_id for task in tasks] == [
        "T-1.1",
        "T-1.2",
        "T-1.3",
        "T-1.4",
        "T-1.5",
        "T-2.1",
    ]
    assert [task.dd_id for task in tasks] == [
        "DD-1",
        "DD-3",
        "DD-3",
        "DD-2",
        "DD-2",
        "DD-4",
    ]
    assert [task.fr_id for task in tasks] == [
        "FR-1",
        "FR-1",
        "FR-1",
        "FR-1",
        "FR-1",
        "FR-2",
    ]


def test_parse_plan_tasks_preserves_each_tasks_dependency_text() -> None:
    tasks = {task.task_id: task for task in parse_plan_tasks(REAL_PLAN_MD)}

    assert "No dependencies" in tasks["T-1.1"].description
    assert "No dependencies" in tasks["T-1.2"].description
    assert "Depends on: T-1.2." in tasks["T-1.3"].description
    assert "No dependencies" in tasks["T-1.4"].description
    assert "Depends on: T-1.1, T-1.3, T-1.4." in tasks["T-1.5"].description
    assert "Depends on: T-1.1, T-1.3." in tasks["T-2.1"].description


MULTILINE_PLAN_MD = """# Plan

## FR-1: Shorten a long URL
- T-1.2 (DD-3): Implement CSPRNG short-code generation —
  `src/service/codes.py` (`generate_code`, `CODE_ALPHABET`, `CODE_LENGTH`).
  No dependencies.
- T-1.3 (DD-3): Implement the thread-safe in-memory `URLStore` in
  `src/service/storage.py`. Depends on: T-1.2.
- T-1.4 (DD-2): Implement `is_valid_url` in `src/service/urls.py`.
  No dependencies.
"""


def test_parse_plan_tasks_captures_continuation_lines_not_just_the_first_line() -> None:
    """T9.9: a real run's task entries wrapped onto continuation lines
    (long descriptions the planner broke across multiple lines); the
    prompt the developer actually received was truncated to the first
    line ("Implement the thread-safe in-memory URLStore in" -- with
    `src/service/storage.py` never reaching the agent). Each task's
    description must now include every continuation line up to the next
    task, not just its own first line.
    """
    tasks = {task.task_id: task for task in parse_plan_tasks(MULTILINE_PLAN_MD)}

    assert len(tasks) == 3
    assert "src/service/codes.py" in tasks["T-1.2"].description
    assert "CODE_ALPHABET" in tasks["T-1.2"].description
    assert "src/service/storage.py" in tasks["T-1.3"].description
    assert "Depends on: T-1.2." in tasks["T-1.3"].description
    # T-1.3's continuation lines must not leak into T-1.2's description, or
    # vice versa -- each task's text stops at the next task line.
    assert "src/service/storage.py" not in tasks["T-1.2"].description
    assert "src/service/codes.py" not in tasks["T-1.3"].description
    assert "No dependencies" in tasks["T-1.4"].description


def test_parse_fr_to_req_also_matches_real_titled_headings() -> None:
    """The same regex drift (T9.8) affected parse_fr_to_req too -- a real
    01-requirements.md's `## FR-n: <title>` headings would have made every
    S5a commit's Req trailer silently empty."""
    requirements_md = (
        "# Requirements\n\n## FR-1: Shorten a long URL\nCites: REQ-2\nbody.\n"
    )

    assert parse_fr_to_req(requirements_md) == {"FR-1": "REQ-2"}
