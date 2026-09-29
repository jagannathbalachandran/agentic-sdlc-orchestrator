"""Smoke test proving the scaffold's package imports and quality gates run clean.

Real unit tests replace/extend this once S5a adds application modules.
"""

from __future__ import annotations

import service


def test_package_exposes_a_version() -> None:
    assert service.__version__ == "0.1.0"
