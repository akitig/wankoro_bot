import json
import os
from pathlib import Path

import pytest

from storage.json_store import load_json, load_json_or_default, save_json_atomic


def test_load_json_reads_valid_file(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    path.write_text('{"count": 3}', encoding="utf-8")

    assert load_json(path) == {"count": 3}


def test_load_json_or_default_for_missing_file(tmp_path: Path) -> None:
    default = {"users": []}

    loaded = load_json_or_default(tmp_path / "missing.json", default)

    assert loaded == default
    assert loaded is not default


def test_save_json_atomic_writes_valid_json(tmp_path: Path) -> None:
    path = tmp_path / "state.json"

    save_json_atomic(path, {"count": 4})

    assert json.loads(path.read_text(encoding="utf-8")) == {"count": 4}


def test_save_and_load_japanese_data(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    data = {"message": "わんころ", "items": ["灯麗会"]}

    save_json_atomic(path, data)

    assert load_json(path) == data
    assert "わんころ" in path.read_text(encoding="utf-8")


def test_failed_serialization_preserves_original_file(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    original = b'{"stable": true}'
    path.write_bytes(original)

    with pytest.raises(TypeError):
        save_json_atomic(path, {"invalid": object()})

    assert path.read_bytes() == original
    assert list(tmp_path.iterdir()) == [path]


def test_failed_replace_preserves_original_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "state.json"
    original = b'{"stable": true}'
    path.write_bytes(original)

    def fail_replace(source: os.PathLike[str], destination: os.PathLike[str]) -> None:
        raise OSError("simulated replace failure")

    monkeypatch.setattr(os, "replace", fail_replace)

    with pytest.raises(OSError, match="simulated replace failure"):
        save_json_atomic(path, {"stable": False})

    assert path.read_bytes() == original
    assert list(tmp_path.iterdir()) == [path]


def test_load_json_raises_for_invalid_json_without_logging_contents(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    path = tmp_path / "broken.json"
    path.write_text('{"private": ', encoding="utf-8")

    with pytest.raises(json.JSONDecodeError):
        load_json_or_default(path, {})

    assert "Invalid JSON file" in caplog.text
    assert "private" not in caplog.text


def test_save_json_atomic_creates_parent_directories(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "runtime" / "state.json"

    save_json_atomic(path, {"ready": True})

    assert load_json(path) == {"ready": True}
