import importlib
import json
from pathlib import Path

import pytest

from repositories.joya_repository import JoyaRepository

joya = importlib.import_module("services.joya_service")


def _service_with_repository(path: Path):
    service = joya.JoyaService.__new__(joya.JoyaService)
    service._repository = JoyaRepository(path)
    service._min_env = 60
    service._max_env = 300
    return service


def test_initial_and_saved_state_structure(tmp_path: Path) -> None:
    path = tmp_path / "joya.json"
    service = _service_with_repository(path)
    repository = service._repository

    assert service._get_count_state(10) == (0, False)
    assert repository.get_guild(10) == {}
    assert repository.get_user(10, 20) == {}

    repository.get_guild(10)["count"] = 1
    repository.get_user(10, 20)["next_ts"] = 1234
    repository.save()

    assert json.loads(path.read_text(encoding="utf-8")) == {
        "guilds": {"10": {"count": 1}},
        "users": {"10:20": {"next_ts": 1234}},
    }


@pytest.mark.parametrize(
    ("count", "expected"),
    [
        (0, (1, False)),
        (106, (107, False)),
        (107, (108, True)),
        (108, (108, True)),
    ],
)
def test_winner_boundary(count: int, expected: tuple[int, bool]) -> None:
    assert joya._advance_count(count) == expected


def test_cooldown_choice_clamps_swaps_and_uses_fixed_random(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[tuple[int, int]] = []

    def fixed_randint(minimum: int, maximum: int) -> int:
        captured.append((minimum, maximum))
        return 42

    monkeypatch.setattr(joya.random, "randint", fixed_randint)

    assert joya._choose_cooldown(5000, 2) == 42
    assert captured == [(5, 3600)]


def test_cooldown_remaining_boundaries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = 1_000
    monkeypatch.setattr(joya, "_now_ts", lambda: now)
    service = _service_with_repository(tmp_path / "joya.json")

    service._set_cooldown(10, 20, 30)

    assert service._cooldown_left(10, 20) == 30
    monkeypatch.setattr(joya, "_now_ts", lambda: 1_030)
    assert service._cooldown_left(10, 20) == 0
    monkeypatch.setattr(joya, "_now_ts", lambda: 1_031)
    assert service._cooldown_left(10, 20) == 0


def test_winner_state_persistence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "joya.json"
    monkeypatch.setattr(joya, "_now_ts", lambda: 1_234_567)
    service = _service_with_repository(path)

    service._set_count_state(10, 108, True, winner_id=20)

    assert json.loads(path.read_text(encoding="utf-8")) == {
        "guilds": {
            "10": {
                "count": 108,
                "finished": True,
                "winner_user_id": 20,
                "finished_at": 1_234_567,
            }
        },
        "users": {},
    }


def test_reset_removes_only_target_guild_state(tmp_path: Path) -> None:
    repository = JoyaRepository(tmp_path / "joya.json")
    repository.get_guild(10)["count"] = 5
    repository.get_guild(11)["count"] = 6
    repository.get_user(10, 20)["next_ts"] = 100
    repository.get_user(10, 21)["next_ts"] = 200
    repository.get_user(11, 20)["next_ts"] = 300

    assert repository.reset_guild_users(10) == 2
    assert json.loads((tmp_path / "joya.json").read_text(encoding="utf-8")) == {
        "guilds": {"10": {}, "11": {"count": 6}},
        "users": {"11:20": {"next_ts": 300}},
    }
