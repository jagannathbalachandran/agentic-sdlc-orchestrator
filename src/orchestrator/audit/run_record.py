"""Atomic run-record I/O: run.json, graph.json (requirements.md §11).

Writes go to a temp file in the same directory, then `os.replace` — a reader never
observes a partially written file, even if the process is interrupted mid-write.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from orchestrator.exceptions import RunRecordError

ModelT = TypeVar("ModelT", bound=BaseModel)


def atomic_write_json(path: Path, model: BaseModel) -> None:
    """Write `model` to `path` as JSON, atomically (write-temp, then os.replace)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(model.model_dump_json(indent=2))
        os.replace(tmp_name, path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def read_json(path: Path, model: type[ModelT]) -> ModelT:
    """Read and validate `path` as `model`."""
    if not path.is_file():
        raise RunRecordError(str(path), "file not found")
    try:
        return model.model_validate_json(path.read_text(encoding="utf-8"))
    except ValidationError as exc:
        raise RunRecordError(str(path), str(exc)) from exc
