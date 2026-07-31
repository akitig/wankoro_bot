import asyncio
import logging

import pytest

import cogs.dm_forward as dm_module
from cogs.dm_forward import DmForwardCog
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


def test_missing_forward_target_is_logged_without_message_body(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(dm_module.discord, "DMChannel", FakeDMChannel)
    bot = FakeBot()
    bot.fetch_error = LookupError("target missing")
    body = "do-not-log-this-body"

    with caplog.at_level(logging.ERROR):
        asyncio.run(
            _cog(bot).on_message(
                FakeMessage(FakeAuthor(800), FakeDMChannel(), content=body)
            )
        )

    assert "Failed to resolve DM forwarding target" in caplog.text
    assert body not in caplog.text


def test_send_failure_is_logged_without_author_or_body(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(dm_module.discord, "DMChannel", FakeDMChannel)
    target = FakeMember(700)

    async def fail_send(*args, **kwargs):
        raise RuntimeError("transport unavailable")

    target.send = fail_send
    bot = FakeBot()
    bot.users[700] = target
    author = FakeAuthor(800, name="private-member-name")
    body = "private-message-body"

    with caplog.at_level(logging.ERROR):
        asyncio.run(
            _cog(bot).on_message(
                FakeMessage(author, FakeDMChannel(), content=body)
            )
        )

    assert "Failed to forward direct message" in caplog.text
    assert author.name not in caplog.text
    assert body not in caplog.text
