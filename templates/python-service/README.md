# Service

Greenfield scaffold for an orchestrator-run project: packaging, CI, and the
quality gates a run's stages check against (`scripts/check.py`).

## Setup

```
pip install -e ".[dev]"
python scripts/check.py
```

`pip install -e ".[dev]"` must run before `scripts/check.py` — the gates
(mypy, pytest) need the package importable first.

## Layout

- `src/service/` — application code (replace the scaffold module).
- `tests/unit/` — unit tests, one per implementation task.
- `tests/acceptance/` — acceptance tests, one per FR's acceptance criterion.
- `.orchestrator/project.toml` — this project's orchestrator config.
