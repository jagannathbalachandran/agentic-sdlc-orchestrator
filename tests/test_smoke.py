"""Smoke test verifying the package is importable and versioned."""

from __future__ import annotations

import orchestrator


def test_version_is_set() -> None:
    assert orchestrator.__version__ == "0.1.0"
