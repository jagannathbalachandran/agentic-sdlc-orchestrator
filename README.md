# agentic-sdlc-orchestrator
An agentic orchestration layer that drives Python software projects through the full
SDLC — requirements, design, implementation, testing, documentation and release
readiness — with governance: quality gates, policy guardrails, human approval
checkpoints and a complete audit trail.

## Setup

### Windows (PowerShell)

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

### Linux/macOS (bash)

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Running the gates

```
python scripts/check.py
```

This runs `ruff check`, `ruff format --check`, `mypy --strict`, `pytest` (with
coverage) and `pip-audit`, stopping at the first failing gate.