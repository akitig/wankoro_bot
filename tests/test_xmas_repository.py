import json
from pathlib import Path

import pytest

from repositories.xmas_repository import STATE_NONE, XmasRepository


def test_missing_file_uses_initial_structure(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    repository = XmasRepository(path)

    repository.load()
    repository.save()

    assert json.loads(path.read_text(encoding="utf-8")) == {
        "orig_nick": {},
        "panel_message_id": 0,
    }


@pytest.mark.parametrize(
    ("existing", "expected"),
    [
        ({}, {"orig_nick": {}, "panel_message_id": 0}),
        ({"orig_nick": {"10": {"20": "名前"}}}, {
            "orig_nick": {"10": {"20": "名前"}},
            "panel_message_id": 0,
        }),
        ({"panel_message_id": 99}, {"orig_nick": {}, "panel_message_id": 99}),
    ],
)
def test_loads_json_and_fills_missing_fields(
    tmp_path: Path,
    existing: dict,
    expected: dict,
) -> None:
    path = tmp_path / "state.json"
    path.write_text(json.dumps(existing, ensure_ascii=False), encoding="utf-8")
    repository = XmasRepository(path)

    repository.load()
    repository.save()

    assert json.loads(path.read_text(encoding="utf-8")) == expected


def test_original_nickname_keys_first_save_sentinel_delete_and_round_trip(
    tmp_path: Path,
) -> None:
    path = tmp_path / "nested" / "state" / "xmas.json"
    repository = XmasRepository(path)
    repository.load()

    assert repository.get_original_nickname(10, 20) is None
    assert repository.save_original_nickname(10, 20, "元の名前") is True
    assert repository.save_original_nickname(10, 20, "上書き禁止") is False
    assert repository.save_original_nickname(10, 21, None) is True
    assert repository.get_original_nickname(10, 20) == "元の名前"
    assert repository.get_original_nickname(10, 21) == STATE_NONE
    assert repository.get_original_user_ids(10) == [20, 21]
    repository.save()

    assert json.loads(path.read_text(encoding="utf-8")) == {
        "orig_nick": {"10": {"20": "元の名前", "21": "__NONE__"}},
        "panel_message_id": 0,
    }
    loaded = XmasRepository(path)
    loaded.load()
    assert loaded.get_original_nickname(10, 20) == "元の名前"
    assert loaded.delete_original_nickname(10, 20) is True
    assert loaded.delete_original_nickname(10, 20) is False


def test_panel_message_id_get_set_and_save(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    repository = XmasRepository(path)
    repository.load()

    assert repository.get_panel_message_id() == 0
    repository.set_panel_message_id(999)
    repository.save()

    assert json.loads(path.read_text(encoding="utf-8"))["panel_message_id"] == 999


def test_invalid_json_is_not_silently_replaced(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    invalid = "{not valid json"
    path.write_text(invalid, encoding="utf-8")
    repository = XmasRepository(path)

    with pytest.raises(json.JSONDecodeError):
        repository.load()

    assert path.read_text(encoding="utf-8") == invalid


def test_failed_save_does_not_damage_existing_file(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    original = '{"orig_nick": {}, "panel_message_id": 0}'
    path.write_text(original, encoding="utf-8")
    repository = XmasRepository(path)
    repository.load()
    repository._state["invalid"] = object()

    with pytest.raises(TypeError):
        repository.save()

    assert path.read_text(encoding="utf-8") == original
