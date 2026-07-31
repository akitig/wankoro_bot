import asyncio
import logging
from types import SimpleNamespace

import pytest

from services.dm_forward_service import DmForwardService
from tests.helpers.discord_fakes import FakeAuthor, FakeMessage


class Target:
    def __init__(self, *, fail_calls: set[int] | None = None) -> None:
        self.sent: list[str] = []
        self.calls = 0
        self.fail_calls = fail_calls or set()

    async def send(self, content: str) -> None:
        self.calls += 1
        if self.calls in self.fail_calls:
            raise RuntimeError("Discord send failed")
        self.sent.append(content)


class BotStub:
    def __init__(
        self,
        *,
        cached: Target | None = None,
        fetched: Target | None = None,
        fetch_error: Exception | None = None,
    ) -> None:
        self.cached = cached
        self.fetched = fetched
        self.fetch_error = fetch_error
        self.get_calls: list[int] = []
        self.fetch_calls: list[int] = []

    def get_user(self, user_id: int) -> Target | None:
        self.get_calls.append(user_id)
        return self.cached

    async def fetch_user(self, user_id: int) -> Target:
        self.fetch_calls.append(user_id)
        if self.fetch_error:
            raise self.fetch_error
        assert self.fetched is not None
        return self.fetched


def _message(
    *,
    content: str = "message body",
    attachment_count: int = 0,
) -> FakeMessage:
    attachments = [
        SimpleNamespace(url=f"https://invalid/private-{index}")
        for index in range(attachment_count)
    ]
    return FakeMessage(
        FakeAuthor(800, name="private-author"),
        object(),
        content=content,
        attachments=attachments,
    )


def test_cached_target_is_used_without_fetch() -> None:
    target = Target()
    bot = BotStub(cached=target)

    asyncio.run(DmForwardService(bot, 700).forward_message(_message()))

    assert bot.get_calls == [700]
    assert bot.fetch_calls == []
    assert len(target.sent) == 1


def test_missing_cached_target_is_fetched() -> None:
    target = Target()
    bot = BotStub(fetched=target)

    asyncio.run(DmForwardService(bot, 700).forward_message(_message()))

    assert bot.get_calls == [700]
    assert bot.fetch_calls == [700]
    assert len(target.sent) == 1


def test_body_and_header_are_forwarded_in_one_message() -> None:
    target = Target()
    message = _message(content="private body")

    asyncio.run(
        DmForwardService(BotStub(cached=target), 700).forward_message(message)
    )

    assert target.sent == [
        "📩 **DM転送**\n"
        "From: **private-author** (`800`)\n"
        "private body"
    ]


@pytest.mark.parametrize("content", ["", "   "])
def test_empty_body_uses_existing_placeholder(content: str) -> None:
    target = Target()

    asyncio.run(
        DmForwardService(BotStub(cached=target), 700).forward_message(
            _message(content=content)
        )
    )

    assert target.sent[0].endswith("（本文なし）")


@pytest.mark.parametrize(
    ("attachment_count", "expected_sends"),
    [(0, 1), (1, 2), (10, 11), (11, 11)],
)
def test_attachment_limit(
    attachment_count: int,
    expected_sends: int,
) -> None:
    target = Target()

    asyncio.run(
        DmForwardService(BotStub(cached=target), 700).forward_message(
            _message(attachment_count=attachment_count)
        )
    )

    assert len(target.sent) == expected_sends
    for index, sent in enumerate(target.sent[1:]):
        assert sent == f"📎 添付: https://invalid/private-{index}"


def test_body_failure_stops_before_attachments(
    caplog: pytest.LogCaptureFixture,
) -> None:
    target = Target(fail_calls={1})
    body = "private body must not be logged"

    with caplog.at_level(logging.ERROR):
        asyncio.run(
            DmForwardService(BotStub(cached=target), 700).forward_message(
                _message(content=body, attachment_count=2)
            )
        )

    assert target.calls == 1
    assert "Failed to forward a DM message" in caplog.text
    assert body not in caplog.text


def test_attachment_failure_logs_and_continues_without_url(
    caplog: pytest.LogCaptureFixture,
) -> None:
    target = Target(fail_calls={2})
    failed_url = "https://invalid/private-0"

    with caplog.at_level(logging.ERROR):
        asyncio.run(
            DmForwardService(BotStub(cached=target), 700).forward_message(
                _message(attachment_count=2)
            )
        )

    assert target.calls == 3
    assert target.sent[-1] == "📎 添付: https://invalid/private-1"
    assert "Failed to forward a DM attachment" in caplog.text
    assert failed_url not in caplog.text


def test_target_resolution_failure_logs_without_message_data(
    caplog: pytest.LogCaptureFixture,
) -> None:
    body = "private body must not be logged"
    bot = BotStub(fetch_error=LookupError("target unavailable"))

    with caplog.at_level(logging.ERROR):
        asyncio.run(
            DmForwardService(bot, 700).forward_message(_message(content=body))
        )

    assert "Failed to resolve the configured DM forwarding target" in caplog.text
    assert body not in caplog.text
    assert "private-author" not in caplog.text
