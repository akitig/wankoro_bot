import json
from pathlib import Path

import pytest

from repositories.valomap_repository import ValomapRepository


def test_missing_file_loads_empty_bans_and_saves_compatible_shape(
    tmp_path: Path,
) -> None:
    path = tmp_path / "bans.json"
    repository = ValomapRepository(path)

    repository.load()
    repository.save()

    assert repository.get_bans() == set()
    assert json.loads(path.read_text(encoding="utf-8")) == {"bans": []}


def test_loads_normal_json_and_returns_independent_ban_set(tmp_path: Path) -> None:
    path = tmp_path / "bans.json"
    path.write_text('{"bans": ["Ascent", "Bind", "Ascent"]}', encoding="utf-8")
    repository = ValomapRepository(path)

    repository.load()
    bans = repository.get_bans()
    bans.add("Lotus")

    assert repository.get_bans() == {"Ascent", "Bind"}


def test_add_duplicate_remove_missing_clear_and_save(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "runtime" / "bans.json"
    repository = ValomapRepository(path)
    repository.load()

    assert repository.add_ban("Ascent") is True
    assert repository.add_ban("Ascent") is False
    assert repository.add_ban("パール") is True
    assert repository.remove_ban("Missing") is False
    assert repository.remove_ban("Ascent") is True
    repository.save()

    assert json.loads(path.read_text(encoding="utf-8")) == {"bans": ["パール"]}
    loaded = ValomapRepository(path)
    loaded.load()
    assert loaded.get_bans() == {"パール"}
    assert loaded.clear_bans() is True
    assert loaded.clear_bans() is False
    loaded.save()
    assert json.loads(path.read_text(encoding="utf-8")) == {"bans": []}


def test_invalid_json_is_not_silently_replaced(tmp_path: Path) -> None:
    path = tmp_path / "bans.json"
    invalid = "{not valid json"
    path.write_text(invalid, encoding="utf-8")
    repository = ValomapRepository(path)

    with pytest.raises(json.JSONDecodeError):
        repository.load()

    assert path.read_text(encoding="utf-8") == invalid


def test_failed_save_does_not_damage_existing_file(tmp_path: Path) -> None:
    path = tmp_path / "bans.json"
    original = '{"bans": ["Ascent"]}'
    path.write_text(original, encoding="utf-8")
    repository = ValomapRepository(path)
    repository.load()
    repository._bans.add(object())  # type: ignore[arg-type]

    with pytest.raises(TypeError):
        repository.save()

    assert path.read_text(encoding="utf-8") == original
