"""Thin StageSpec bindings, one per stage (requirements.md §7) — not per-stage
packages: all nine stages share identical gate/policy/event-emission plumbing in
engine/runner.py, so there's nothing stage-specific to hold here beyond the spec.
"""
