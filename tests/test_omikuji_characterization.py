import asyncio
import json
from collections import Counter
from pathlib import Path

import pytest

import services.omikuji_service as omikuji


def test_point_lifecycle_and_persisted_user_key(tmp_path: Path) -> None:
    path = tmp_path / "omikuji.json"
    service = omikuji.OmikujiService(
        object(),
        points_path=str(path),
        rest_vc_id=0,
        resetter_user_id=0,
        panel_channel_id=0,
    )

    async def scenario() -> None:
        await service.load()
        assert await service.get_points(12345) == 0

        await service.ensure_initial_points(12345, 500)
        await service.ensure_initial_points(12345, 999)
        assert await service.get_points(12345) == 500
        assert await service.add_points(12345, 25) == 525
        assert await service.add_points(12345, -600) == 0

        await service.ensure_initial_points(67890, 300)
        assert await service.reset_all_points(500) == 2
        await service.save()

    asyncio.run(scenario())

    assert json.loads(path.read_text(encoding="utf-8")) == {
        "12345": 500,
        "67890": 500,
    }


def test_load_filters_non_numeric_user_keys(tmp_path: Path) -> None:
    path = tmp_path / "omikuji.json"
    path.write_text('{"123": 20, "not-user": 99}', encoding="utf-8")
    service = omikuji.OmikujiService(
        object(),
        points_path=str(path),
        rest_vc_id=0,
        resetter_user_id=0,
        panel_channel_id=0,
    )

    asyncio.run(service.load())

    assert asyncio.run(service.get_points(123)) == 20
    assert service._points == {"123": 20}


def test_omikuji_weight_table_and_random_choice_are_fixed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[str] = []

    def choose(pool: list[str]) -> str:
        captured.extend(pool)
        return "大吉"

    monkeypatch.setattr(omikuji.random, "choice", choose)
    assert omikuji.OmikujiService._draw_omikuji() == "大吉"
    assert Counter(captured) == {
        "大吉": 6,
        "中吉": 14,
        "小吉": 22,
        "吉": 26,
        "末吉": 20,
        "凶": 10,
        "大凶": 2,
    }
