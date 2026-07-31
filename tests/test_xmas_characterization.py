import json
from datetime import datetime
from pathlib import Path

import pytest

import services.xmas_service as xmas


def _service(tmp_path: Path, *, cutoff: str = "2025-12-26T07:00:00+09:00"):
    return xmas.XmasService(
        object(),
        csv_path=tmp_path / "rewards.csv",
        state_path=tmp_path / "xmas-state.json",
        channel_id=0,
        cutoff=cutoff,
        panel_view_factory=lambda: object(),
        result_view_factory=lambda: object(),
    )


def test_initial_state_and_nickname_round_trip(tmp_path: Path) -> None:
    service = _service(tmp_path)
    repository = service._repository
    repository.save_original_nickname(10, 20, "元の名前")
    repository.save_original_nickname(10, 21, None)
    repository.set_panel_message_id(999)
    repository.save()

    saved = json.loads((tmp_path / "xmas-state.json").read_text(encoding="utf-8"))
    assert saved == {
        "orig_nick": {"10": {"20": "元の名前", "21": xmas.STATE_NONE}},
        "panel_message_id": 999,
    }
    assert repository.get_original_nickname(10, 20) == "元の名前"
    assert repository.get_original_nickname(10, 21) == xmas.STATE_NONE
    repository.delete_original_nickname(10, 20)
    assert repository.get_original_nickname(10, 20) is None


def test_state_read_fills_existing_missing_fields(tmp_path: Path) -> None:
    path = tmp_path / "xmas-state.json"
    path.write_text("{}", encoding="utf-8")

    service = _service(tmp_path)
    service._repository.save()
    assert json.loads(path.read_text(encoding="utf-8")) == {
        "orig_nick": {},
        "panel_message_id": 0,
    }


def test_csv_reward_parsing_preserves_existing_rules(tmp_path: Path) -> None:
    path = tmp_path / "rewards.csv"
    path.write_text(
        "weight,rarity,icon,title,name,desc\n"
        "10,UR,🎁,特賞,犬のお守り,日本語説明\n"
        "0,R,⭐,重みゼロ,無視,ignored\n"
        "bad,SR,🌙,不正重み,無視,ignored\n"
        "5,N,🍪,,タイトルなし,ignored\n"
        "5,N,🍪,名前なし,,ignored\n"
        "\n",
        encoding="utf-8",
    )
    service = _service(tmp_path)

    assert service.read_csv_rewards() == [
        xmas.t_reward(10, "UR", "🎁", "特賞", "犬のお守り", "日本語説明")
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

    assert xmas.XmasService.pick_reward([first, second]) is second
    assert captured == {
        "rewards": [first, second],
        "weights": [2, 7],
        "k": 1,
    }


def test_cutoff_is_open_before_and_closed_at_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service(tmp_path)
    monkeypatch.setattr(
        service,
        "_now_jst",
        lambda: datetime.fromisoformat("2025-12-26T06:59:59+09:00"),
    )
    assert service.is_closed() is False
    monkeypatch.setattr(
        service,
        "_now_jst",
        lambda: datetime.fromisoformat("2025-12-26T07:00:00+09:00"),
    )
    assert service.is_closed() is True
    monkeypatch.setattr(
        service,
        "_now_jst",
        lambda: datetime.fromisoformat("2025-12-26T07:00:01+09:00"),
    )
    assert service.is_closed() is True
