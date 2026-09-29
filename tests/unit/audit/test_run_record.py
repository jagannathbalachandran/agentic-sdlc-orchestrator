"""Tests for orchestrator.audit.run_record."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import BaseModel

from orchestrator.audit.run_record import atomic_write_json, read_json
from orchestrator.exceptions import RunRecordError


class _SampleModel(BaseModel):
    value: str


class _ExplodingModel(BaseModel):
    """Test double whose serialization always fails, to simulate a mid-write crash."""

    def model_dump_json(self, *args: object, **kwargs: object) -> str:
        raise RuntimeError("simulated crash mid-write")


def test_atomic_write_then_read_json_round_trips(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "run.json"
    atomic_write_json(path, _SampleModel(value="hello"))
    assert read_json(path, _SampleModel).value == "hello"


def test_read_json_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(RunRecordError):
        read_json(tmp_path / "does-not-exist.json", _SampleModel)


def test_read_json_rejects_malformed_content(tmp_path: Path) -> None:
    path = tmp_path / "run.json"
    path.write_text("not valid json", encoding="utf-8")
    with pytest.raises(RunRecordError):
        read_json(path, _SampleModel)


def test_atomic_write_json_leaves_original_file_untouched_on_interrupted_write(
    tmp_path: Path,
) -> None:
    path = tmp_path / "run.json"
    atomic_write_json(path, _SampleModel(value="original"))
    original_bytes = path.read_bytes()

    with pytest.raises(RuntimeError):
        atomic_write_json(path, _ExplodingModel())

    assert path.read_bytes() == original_bytes
    assert list(tmp_path.glob(f".{path.name}.*")) == []
