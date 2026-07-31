import asyncio
import importlib
import json
from collections import Counter
from pathlib import Path

import pytest

omikuji = importlib.import_module("cogs.2026_omikuji_gacha")


def test_point_lifecycle_and_persisted_user_key(tmp_path: Path) -> None:
    path = tmp_path / "omikuji.json"
    store = omikuji.OmikujiStore(str(path))

    async def scenario() -> None:
        await store.load()
        assert await store.get(12345) == 0

        await store.ensure_initial(12345, 500)
        await store.ensure_initial(12345, 999)
        assert await store.get(12345) == 500
        assert await store.add(12345, 25) == 525
        assert await store.add(12345, -600) == 0

        await store.ensure_initial(67890, 300)
        assert await store.reset_all(500) == 2
        await store.save()

    asyncio.run(scenario())

    assert json.loads(path.read_text(encoding="utf-8")) == {
        "12345": 500,
        "67890": 500,
    }


def test_load_filters_non_numeric_user_keys(tmp_path: Path) -> None:
    path = tmp_path / "omikuji.json"
    path.write_text('{"123": 20, "not-user": 99}', encoding="utf-8")
    store = omikuji.OmikujiStore(str(path))

    asyncio.run(store.load())

    assert asyncio.run(store.get(123)) == 20
    assert store._points == {"123": 20}


def test_omikuji_weight_table_and_random_choice_are_fixed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[str] = []

    def choose(pool: list[str]) -> str:
        captured.extend(pool)
        return "大吉"

    monkeypatch.setattr(omikuji.random, "choice", choose)
    cog = omikuji.OmikujiGachaCog.__new__(omikuji.OmikujiGachaCog)

    assert cog._draw_omikuji() == "大吉"
    assert Counter(captured) == {
        "大吉": 6,
        "中吉": 14,
        "小吉": 22,
        "吉": 26,
        "末吉": 20,
        "凶": 10,
        "大凶": 2,
    }
