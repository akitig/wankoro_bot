import asyncio
import logging
from types import SimpleNamespace

import pytest

import cogs.leave_log as leave_module
from cogs.leave_log import LeaveLog
from tests.helpers.discord_fakes import FakeChannel, FakeGuild, FakeMember, FakeRole


def _cog(channel: FakeChannel | None) -> LeaveLog:
    cog = LeaveLog.__new__(LeaveLog)
    cog.LEAVE_LOG_CHANNEL_ID = 700
    cog.recent_bans = {}
    cog.recent_kicks = {}
    return cog


def _member(channel: FakeChannel | None) -> tuple[FakeMember, FakeGuild]:
    guild = FakeGuild(
        guild_id=100,
        channels={700: channel} if channel else {},
    )
    member = FakeMember(500, name="private-member", roles=[guild.default_role, FakeRole(9)])
    member.guild = guild
    return member, guild


@pytest.fixture
def no_leave_delay(monkeypatch: pytest.MonkeyPatch) -> None:
    async def no_sleep(seconds: float) -> None:
        return None

    monkeypatch.setattr(leave_module.asyncio, "sleep", no_sleep)


@pytest.mark.parametrize(
    ("state_name", "expected_title"),
    [
        (None, "📕 退出者が出ました"),
        ("recent_kicks", "🦶 ユーザーが追放されました"),
        ("recent_bans", "🕊️ ユーザーがBANされました"),
    ],
)
def test_leave_kick_and_ban_notifications(
    state_name: str | None,
    expected_title: str,
    no_leave_delay: None,
) -> None:
    channel = FakeChannel()
    member, _guild = _member(channel)
    cog = _cog(channel)
    if state_name:
        getattr(cog, state_name)[member.id] = "private-reason"

    asyncio.run(cog.on_member_remove(member))

    embed = channel.sent[0][1]["embed"]
    assert embed.title == expected_title
    if state_name:
        assert any(field.value == "private-reason" for field in embed.fields)


def test_missing_notification_channel_logs_warning_without_member(
    caplog: pytest.LogCaptureFixture,
) -> None:
    member, _guild = _member(None)
    cog = _cog(None)

    with caplog.at_level(logging.WARNING):
        asyncio.run(cog.on_member_remove(member))

    assert "Leave log channel is unavailable" in caplog.text
    assert member.name not in caplog.text


def test_ban_audit_fetch_failure_uses_default_and_logs_without_member(
    caplog: pytest.LogCaptureFixture,
) -> None:
    guild = FakeGuild()
    user = FakeMember(500, name="private-member")

    async def fail_fetch_ban(target):
        raise RuntimeError("audit unavailable")

    guild.fetch_ban = fail_fetch_ban
    cog = _cog(FakeChannel())

    with caplog.at_level(logging.ERROR):
        asyncio.run(cog.on_member_ban(guild, user))

    assert cog.recent_bans[user.id] == "理由なし"
    assert "Failed to fetch ban details" in caplog.text
    assert user.name not in caplog.text


def test_ban_reason_is_not_written_to_process_log(
    caplog: pytest.LogCaptureFixture,
) -> None:
    guild = FakeGuild()
    user = FakeMember(500, name="private-member")

    async def fetch_ban(target):
        return SimpleNamespace(reason="private moderation reason")

    guild.fetch_ban = fetch_ban
    cog = _cog(FakeChannel())

    with caplog.at_level(logging.INFO):
        asyncio.run(cog.on_member_ban(guild, user))

    assert cog.recent_bans[user.id] == "private moderation reason"
    assert "private moderation reason" not in caplog.text
    assert user.name not in caplog.text


def test_kick_audit_event_records_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(leave_module.discord, "User", FakeMember)
    target = FakeMember(500)
    entry = SimpleNamespace(
        action=leave_module.discord.AuditLogAction.kick,
        target=target,
        reason="policy reason",
    )
    cog = _cog(FakeChannel())

    asyncio.run(cog.on_audit_log_entry_create(entry))

    assert cog.recent_kicks[target.id] == "policy reason"
