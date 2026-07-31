import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import services.omikuji_service as service_module
from services.omikuji_service import OmikujiService


class FakeResponse:
    def __init__(self) -> None:
        self.sent: list[tuple[tuple, dict]] = []

    async def send_message(self, *args, **kwargs) -> None:
        self.sent.append((args, kwargs))


def _service(tmp_path: Path, *, bot=None, resetter_user_id: int = 99) -> OmikujiService:
    return OmikujiService(
        bot if bot is not None else SimpleNamespace(guilds=[]),
        points_path=str(tmp_path / "omikuji.json"),
        rest_vc_id=10,
        resetter_user_id=resetter_user_id,
        panel_channel_id=0,
    )


def test_initial_add_subtract_floor_reset_and_json_save(tmp_path: Path) -> None:
    service = _service(tmp_path)

    async def scenario() -> None:
        await service.load()
        assert await service.get_points(1) == 0
        await service.ensure_initial_points(1, 500)
        await service.ensure_initial_points(1, 999)
        assert await service.get_points(1) == 500
        assert await service.add_points(1, 25) == 525
        assert await service.add_points(1, -50) == 475
        assert await service.add_points(1, -1_000) == 0
        await service.ensure_initial_points(2, 100)
        assert await service.reset_all_points(500) == 2
        await service.save()

    asyncio.run(scenario())

    assert json.loads((tmp_path / "omikuji.json").read_text(encoding="utf-8")) == {
        "1": 500,
        "2": 500,
    }


def test_draw_result_charges_points_and_builds_same_embed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service(tmp_path)
    response = FakeResponse()
    interaction = SimpleNamespace(user=SimpleNamespace(id=1), response=response)
    monkeypatch.setattr(service_module.random, "choice", lambda _pool: "大吉")

    asyncio.run(service.handle_draw(interaction))

    assert asyncio.run(service.get_points(1)) == 450
    assert json.loads((tmp_path / "omikuji.json").read_text(encoding="utf-8")) == {
        "1": 450
    }
    args, kwargs = response.sent[0]
    assert args == ()
    assert kwargs["ephemeral"] is True
    assert kwargs["embed"].title == "🎍 初春おみくじ（2026）"
    assert kwargs["embed"].description == "結果：**大吉**"
    assert kwargs["embed"].fields[0].value == "450pt"


def test_insufficient_points_preserves_message_and_does_not_save(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    response = FakeResponse()
    interaction = SimpleNamespace(user=SimpleNamespace(id=1), response=response)

    async def scenario() -> None:
        await service.ensure_initial_points(1, 49)
        await service.handle_draw(interaction)

    asyncio.run(scenario())

    assert response.sent == [
        (("ポイント不足です（必要：50pt / 現在：49pt）",), {"ephemeral": True})
    ]
    assert not (tmp_path / "omikuji.json").exists()


def test_vc_tick_adds_only_non_bot_members_in_countable_channels(
    tmp_path: Path,
) -> None:
    member = SimpleNamespace(id=1, bot=False)
    bot_member = SimpleNamespace(id=2, bot=True)
    countable = SimpleNamespace(id=11, members=[member, bot_member])
    rest = SimpleNamespace(id=10, members=[SimpleNamespace(id=3, bot=False)])
    bot = SimpleNamespace(guilds=[SimpleNamespace(voice_channels=[countable, rest])])
    service = _service(tmp_path, bot=bot)

    asyncio.run(service.tick_vc_points())

    assert asyncio.run(service.get_points(1)) == 501
    assert asyncio.run(service.get_points(2)) == 0
    assert asyncio.run(service.get_points(3)) == 0


def test_reset_command_resets_authorized_user_state(tmp_path: Path) -> None:
    service = _service(tmp_path)
    response = FakeResponse()
    interaction = SimpleNamespace(user=SimpleNamespace(id=99), response=response)

    async def scenario() -> None:
        await service.ensure_initial_points(1, 10)
        await service.ensure_initial_points(2, 20)
        await service.reset_points(interaction)

    asyncio.run(scenario())

    assert json.loads((tmp_path / "omikuji.json").read_text(encoding="utf-8")) == {
        "1": 500,
        "2": 500,
    }
    assert response.sent == [
        (("ポイントをリセットしました（対象：2人 / 500pt）。",), {"ephemeral": True})
    ]
