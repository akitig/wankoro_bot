import json
from pathlib import Path

import pytest

from repositories.joya_repository import JoyaRepository


def test_missing_file_starts_with_compatible_structure(tmp_path: Path) -> None:
    path = tmp_path / "joya.json"
    repository = JoyaRepository(path)

    repository.save()

    assert json.loads(path.read_text(encoding="utf-8")) == {
        "guilds": {},
        "users": {},
    }


def test_loads_existing_state_and_uses_compatible_keys(tmp_path: Path) -> None:
    path = tmp_path / "joya.json"
    path.write_text(
        json.dumps(
            {
                "guilds": {"10": {"count": 7}},
                "users": {"10:20": {"next_ts": 123}},
            }
        ),
        encoding="utf-8",
    )

    repository = JoyaRepository(path)

    assert repository.get_guild(10) == {"count": 7}
    assert repository.get_user(10, 20) == {"next_ts": 123}
    repository.get_guild(11)["count"] = 1
    repository.get_user(11, 21)["next_ts"] = 456
    repository.save()
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["guilds"]["11"] == {"count": 1}
    assert saved["users"]["11:21"] == {"next_ts": 456}


def test_round_trip_preserves_japanese_panel_and_winner_state(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "state" / "joya.json"
    repository = JoyaRepository(path)
    guild = repository.get_guild(10)
    guild.update(
        {
            "label": "除夜の鐘",
            "count": 108,
            "finished": True,
            "winner_user_id": 20,
            "finished_at": 1_234_567,
            "panel_channel_id": 30,
            "panel_message_id": 40,
        }
    )

    repository.save()

    loaded = JoyaRepository(path).get_guild(10)
    assert loaded == guild
    assert "除夜の鐘" in path.read_text(encoding="utf-8")


def test_reset_removes_only_target_guild_users(tmp_path: Path) -> None:
    path = tmp_path / "joya.json"
    repository = JoyaRepository(path)
    repository.get_guild(10)["count"] = 5
    repository.get_guild(11)["count"] = 6
    repository.get_user(10, 20)["next_ts"] = 100
    repository.get_user(10, 21)["next_ts"] = 200
    repository.get_user(11, 20)["next_ts"] = 300

    assert repository.reset_guild_users(10) == 2

    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved == {
        "guilds": {"10": {}, "11": {"count": 6}},
        "users": {"11:20": {"next_ts": 300}},
    }


def test_invalid_json_is_not_silently_replaced(tmp_path: Path) -> None:
    path = tmp_path / "joya.json"
    invalid = "{not valid json"
    path.write_text(invalid, encoding="utf-8")

    with pytest.raises(json.JSONDecodeError):
        JoyaRepository(path)

    assert path.read_text(encoding="utf-8") == invalid


def test_failed_save_does_not_damage_existing_file(tmp_path: Path) -> None:
    path = tmp_path / "joya.json"
    original = '{"guilds": {}, "users": {}}'
    path.write_text(original, encoding="utf-8")
    repository = JoyaRepository(path)
    repository.get_guild(10)["invalid"] = object()

    with pytest.raises(TypeError):
        repository.save()

    assert path.read_text(encoding="utf-8") == original
