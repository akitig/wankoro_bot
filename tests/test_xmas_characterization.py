import importlib
import json
from datetime import datetime
from pathlib import Path

import pytest

xmas = importlib.import_module("cogs.2025_xmas_gacha")


def test_initial_state_and_nickname_round_trip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "xmas-state.json"
    monkeypatch.setattr(xmas, "STATE_PATH", path)

    state = xmas._state_read()
    assert state == {"orig_nick": {}, "panel_message_id": 0}

    xmas._orig_set(state, 10, 20, "元の名前")
    xmas._orig_set(state, 10, 21, None)
    state["panel_message_id"] = 999
    xmas._state_write(state)

    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved == {
        "orig_nick": {
            "10": {
                "20": "元の名前",
                "21": xmas.STATE_NONE,
            }
        },
        "panel_message_id": 999,
    }
    assert xmas._orig_get(saved, 10, 20) == "元の名前"
    assert xmas._orig_get(saved, 10, 21) == xmas.STATE_NONE

    xmas._orig_clear(saved, 10, 20)
    assert xmas._orig_get(saved, 10, 20) is None


def test_state_read_fills_existing_missing_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "xmas-state.json"
    path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(xmas, "STATE_PATH", path)

    assert xmas._state_read() == {"orig_nick": {}, "panel_message_id": 0}


def test_csv_reward_parsing_preserves_existing_rules(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "rewards.csv"
    path.write_text(
        "weight,rarity,icon,title,name,desc\n"
        "10,UR,🎁,特賞,犬のお守り,日本語説明\n"
        "0,R,⭐,重みゼロ,無視,ignored\n"
        "bad,SR,🌙,不正重み,無視,ignored\n"
        "5,N,🍪,,タイトルなし,ignored\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(xmas, "CSV_PATH", path)

    assert xmas._read_csv_rewards() == [
        xmas.t_reward(
            weight=10,
            rarity="UR",
            icon="🎁",
            title="特賞",
            name="犬のお守り",
            desc="日本語説明",
        )
    ]


def test_weighted_reward_selection_uses_reward_weights(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = xmas.t_reward(2, "R", "", "A", "a", "")
    second = xmas.t_reward(7, "SR", "", "B", "b", "")
    captured: dict[str, object] = {}

    def fixed_choices(rewards, *, weights, k):
        captured.update(rewards=rewards, weights=weights, k=k)
        return [second]

    monkeypatch.setattr(xmas.random, "choices", fixed_choices)

    assert xmas._pick_reward([first, second]) is second
    assert captured == {
        "rewards": [first, second],
        "weights": [2, 7],
        "k": 1,
    }


def test_cutoff_is_open_before_and_closed_at_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(xmas, "CUTOFF_RAW", "2025-12-26T07:00:00+09:00")

    monkeypatch.setattr(
        xmas,
        "_now_jst",
        lambda: datetime.fromisoformat("2025-12-26T06:59:59+09:00"),
    )
    assert xmas._is_closed() is False

    monkeypatch.setattr(
        xmas,
        "_now_jst",
        lambda: datetime.fromisoformat("2025-12-26T07:00:00+09:00"),
    )
    assert xmas._is_closed() is True

    monkeypatch.setattr(
        xmas,
        "_now_jst",
        lambda: datetime.fromisoformat("2025-12-26T07:00:01+09:00"),
    )
    assert xmas._is_closed() is True
