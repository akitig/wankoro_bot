import asyncio

import pytest

import cogs.dm_forward as dm_module
from cogs.dm_forward import DmForwardCog
from services.dm_forward_service import DmForwardService
from tests.helpers.discord_fakes import (
    FakeAuthor,
    FakeBot,
    FakeChannel,
    FakeDMChannel,
    FakeMember,
    FakeMessage,
)


def _cog(bot: FakeBot | None = None) -> DmForwardCog:
    cog = DmForwardCog.__new__(DmForwardCog)
    cog.bot = bot or FakeBot()
    cog.forward_user_id = 700
    cog.service = DmForwardService(cog.bot, cog.forward_user_id)
    return cog


def test_direct_message_is_forwarded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dm_module.discord, "DMChannel", FakeDMChannel)
    target = FakeMember(700)
    bot = FakeBot()
    bot.users[700] = target
    message = FakeMessage(
        FakeAuthor(800),
        FakeDMChannel(),
        content="private message body",
    )

    asyncio.run(_cog(bot).on_message(message))

    assert len(target.sent) == 1
    assert "private message body" in target.sent[0][0][0]


def test_bot_message_is_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dm_module.discord, "DMChannel", FakeDMChannel)
    target = FakeMember(700)
    bot = FakeBot()
    bot.users[700] = target

    asyncio.run(
        _cog(bot).on_message(
            FakeMessage(FakeAuthor(800, bot=True), FakeDMChannel(), content="ignored")
        )
    )

    assert target.sent == []


def test_guild_message_is_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dm_module.discord, "DMChannel", FakeDMChannel)
    target = FakeMember(700)
    bot = FakeBot()
    bot.users[700] = target

    asyncio.run(
        _cog(bot).on_message(
            FakeMessage(FakeAuthor(800), FakeChannel(), content="guild content")
        )
    )

    assert target.sent == []


def test_unconfigured_forward_target_is_ignored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(dm_module.discord, "DMChannel", FakeDMChannel)
    bot = FakeBot()
    cog = _cog(bot)
    cog.forward_user_id = None
    calls = []

    class ServiceStub:
        async def forward_message(self, message):
            calls.append(message)

    cog.service = ServiceStub()

    asyncio.run(
        cog.on_message(
            FakeMessage(FakeAuthor(800), FakeDMChannel(), content="ignored")
        )
    )

    assert calls == []


def test_direct_message_is_delegated_to_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(dm_module.discord, "DMChannel", FakeDMChannel)
    cog = _cog()
    calls = []

    class ServiceStub:
        async def forward_message(self, message):
            calls.append(message)

    cog.service = ServiceStub()
    message = FakeMessage(FakeAuthor(800), FakeDMChannel(), content="forward")

    asyncio.run(cog.on_message(message))

    assert calls == [message]
