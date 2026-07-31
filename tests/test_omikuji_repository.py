import asyncio
import json
from pathlib import Path

import pytest

from repositories.omikuji_repository import OmikujiRepository


def test_missing_file_loads_empty_points_and_unregistered_is_zero(
    tmp_path: Path,
) -> None:
    repository = OmikujiRepository(tmp_path / "omikuji.json")

    asyncio.run(repository.load())

    assert asyncio.run(repository.get_points(123)) == 0


def test_loads_numeric_keys_and_filters_non_numeric_keys(tmp_path: Path) -> None:
    path = tmp_path / "omikuji.json"
    path.write_text('{"123": 20, "456": "30", "not-user": 99}', encoding="utf-8")
    repository = OmikujiRepository(path)

    async def scenario() -> None:
        await repository.load()
        assert await repository.get_points(123) == 20
        assert await repository.get_points(456) == 30
        await repository.save()

    asyncio.run(scenario())

    assert json.loads(path.read_text(encoding="utf-8")) == {"123": 20, "456": 30}


def test_initial_add_consume_floor_reset_and_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "state" / "omikuji.json"
    repository = OmikujiRepository(path)

    async def scenario() -> None:
        await repository.load()
        assert await repository.ensure_initial(123, 500) == 500
        assert await repository.ensure_initial(123, 999) == 500
        assert await repository.add_points(123, 25) == 525
        assert await repository.consume_points(123, 50) == 475
        assert await repository.consume_points(123, 1_000) == 0
        assert await repository.ensure_initial(456, 300) == 300
        assert await repository.reset_all(500) == 2
        await repository.save()

    asyncio.run(scenario())

    assert json.loads(path.read_text(encoding="utf-8")) == {"123": 500, "456": 500}
    loaded = OmikujiRepository(path)
    asyncio.run(loaded.load())
    assert asyncio.run(loaded.get_points(123)) == 500
    assert asyncio.run(loaded.get_points(456)) == 500


def test_concurrent_updates_are_serialized_by_repository_lock(tmp_path: Path) -> None:
    repository = OmikujiRepository(tmp_path / "omikuji.json")

    async def scenario() -> int:
        await repository.ensure_initial(123, 0)
        await asyncio.gather(*(repository.add_points(123, 1) for _ in range(100)))
        return await repository.get_points(123)

    assert asyncio.run(scenario()) == 100


def test_invalid_json_is_not_silently_replaced(tmp_path: Path) -> None:
    path = tmp_path / "omikuji.json"
    invalid = "{not valid json"
    path.write_text(invalid, encoding="utf-8")
    repository = OmikujiRepository(path)

    with pytest.raises(json.JSONDecodeError):
        asyncio.run(repository.load())

    assert path.read_text(encoding="utf-8") == invalid


def test_failed_save_does_not_damage_existing_file(tmp_path: Path) -> None:
    path = tmp_path / "omikuji.json"
    original = '{"123": 500}'
    path.write_text(original, encoding="utf-8")
    repository = OmikujiRepository(path)

    async def scenario() -> None:
        await repository.load()
        repository._points["456"] = object()  # type: ignore[assignment]
        await repository.save()

    with pytest.raises(TypeError):
        asyncio.run(scenario())

    assert path.read_text(encoding="utf-8") == original
