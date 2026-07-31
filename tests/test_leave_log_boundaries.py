import asyncio
import logging
from types import SimpleNamespace

import pytest

from cogs.leave_log import LeaveLog
from tests.helpers.discord_fakes import FakeGuild, FakeMember


class ServiceStub:
    def __init__(self) -> None:
        self.calls = []

    async def handle_member_remove(self, member) -> None:
        self.calls.append(("remove", member))

    async def record_ban(self, guild, user) -> None:
        self.calls.append(("ban", guild, user))

    async def record_audit_log_entry(self, entry) -> None:
        self.calls.append(("audit", entry))


def _cog() -> tuple[LeaveLog, ServiceStub]:
    cog = LeaveLog.__new__(LeaveLog)
    service = ServiceStub()
    cog.service = service
    return cog, service


def test_member_remove_delegates_to_service() -> None:
    cog, service = _cog()
    member = FakeMember(500)

    asyncio.run(cog.on_member_remove(member))

    assert service.calls == [("remove", member)]


def test_member_ban_delegates_to_service() -> None:
    cog, service = _cog()
    guild = FakeGuild()
    user = FakeMember(500)

    asyncio.run(cog.on_member_ban(guild, user))

    assert service.calls == [("ban", guild, user)]


def test_audit_log_event_delegates_to_service() -> None:
    cog, service = _cog()
    entry = SimpleNamespace(action="kick")

    asyncio.run(cog.on_audit_log_entry_create(entry))

    assert service.calls == [("audit", entry)]


def test_on_ready_keeps_existing_log_message(
    caplog: pytest.LogCaptureFixture,
) -> None:
    cog, _service = _cog()

    with caplog.at_level(logging.INFO):
        asyncio.run(cog.on_ready())

    assert "Leave-log event handlers ready" in caplog.text
