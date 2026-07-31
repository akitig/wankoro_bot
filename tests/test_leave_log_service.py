import asyncio
import logging
from types import SimpleNamespace

import pytest

import services.leave_log_service as service_module
from services.leave_log_service import LeaveLogService
from tests.helpers.discord_fakes import FakeChannel, FakeGuild, FakeMember, FakeRole


async def no_sleep(seconds: float) -> None:
    return None


def _service() -> LeaveLogService:
    return LeaveLogService(700, sleep=no_sleep)


def _member(
    channel: FakeChannel | None,
    *,
    roles: list[FakeRole] | None = None,
) -> tuple[FakeMember, FakeGuild]:
    guild = FakeGuild(channels={700: channel} if channel else {})
    member = FakeMember(500, name="private-member", roles=roles or [])
    member.guild = guild
    return member, guild


def _notify(
    service: LeaveLogService,
    member: FakeMember,
    channel: FakeChannel,
):
    asyncio.run(service.handle_member_remove(member))
    return channel.sent[-1][1]["embed"]


def test_missing_channel_logs_without_member_name(
    caplog: pytest.LogCaptureFixture,
) -> None:
    member, _guild = _member(None)

    with caplog.at_level(logging.WARNING):
        asyncio.run(_service().handle_member_remove(member))

    assert "Leave log channel is unavailable" in caplog.text
    assert member.name not in caplog.text


def test_member_remove_waits_one_second_without_real_delay() -> None:
    delays = []

    async def record_sleep(seconds: float) -> None:
        delays.append(seconds)

    channel = FakeChannel()
    member, _guild = _member(channel)
    service = LeaveLogService(700, sleep=record_sleep)

    asyncio.run(service.handle_member_remove(member))

    assert delays == [1]


@pytest.mark.parametrize(
    ("event_type", "title", "color"),
    [
        ("leave", "📕 退出者が出ました", 0xFF6B6B),
        ("kick", "🦶 ユーザーが追放されました", 0xFFD166),
        ("ban", "🕊️ ユーザーがBANされました", 0x6B8AFF),
    ],
)
def test_leave_kick_ban_titles_colors_and_notification(
    event_type: str,
    title: str,
    color: int,
) -> None:
    channel = FakeChannel()
    member, _guild = _member(channel)
    service = _service()
    if event_type == "kick":
        service.recent_kicks[member.id] = "reason"
    elif event_type == "ban":
        service.recent_bans[member.id] = "reason"

    embed = _notify(service, member, channel)

    assert embed.title == title
    assert embed.color.value == color
    assert len(channel.sent) == 1


def test_kick_is_prioritized_and_both_states_pop_as_processed() -> None:
    channel = FakeChannel()
    member, _guild = _member(channel)
    service = _service()
    service.recent_kicks[member.id] = "kick reason"
    service.recent_bans[member.id] = "ban reason"

    first = _notify(service, member, channel)
    second = _notify(service, member, channel)

    assert first.title == "🦶 ユーザーが追放されました"
    assert first.fields[-1].value == "kick reason"
    assert member.id not in service.recent_kicks
    assert second.title == "🕊️ ユーザーがBANされました"
    assert member.id not in service.recent_bans


def test_embed_fields_roles_reason_and_thumbnail_are_preserved() -> None:
    channel = FakeChannel()
    member, guild = _member(channel)
    visible_role = FakeRole(9)
    member.roles = [guild.default_role, visible_role]
    service = _service()
    service.recent_kicks[member.id] = "policy reason"

    embed = _notify(service, member, channel)

    assert [(field.name, field.value) for field in embed.fields] == [
        ("👤 ユーザー:", member.mention),
        ("🆔 ID:", f"`{member.id}`"),
        ("🎭 退出時ロール:", visible_role.mention),
        ("📝 理由:", "policy reason"),
    ]
    assert embed.thumbnail.url == member.display_avatar.url


def test_no_roles_uses_none_and_no_reason_field() -> None:
    channel = FakeChannel()
    member, guild = _member(channel)
    member.roles = [guild.default_role]

    embed = _notify(_service(), member, channel)

    assert [field.value for field in embed.fields] == [
        member.mention,
        f"`{member.id}`",
        "なし",
    ]


@pytest.mark.parametrize(("reason", "expected"), [("ban reason", "ban reason"), (None, "理由なし")])
def test_ban_details_are_saved(reason: str | None, expected: str) -> None:
    guild = FakeGuild()
    user = FakeMember(500)

    async def fetch_ban(target):
        return SimpleNamespace(reason=reason)

    guild.fetch_ban = fetch_ban
    service = _service()

    asyncio.run(service.record_ban(guild, user))

    assert service.recent_bans[user.id] == expected


def test_ban_fetch_failure_logs_and_uses_default_without_private_data(
    caplog: pytest.LogCaptureFixture,
) -> None:
    guild = FakeGuild()
    user = FakeMember(500, name="private-member")

    async def fetch_ban(target):
        raise RuntimeError("audit unavailable")

    guild.fetch_ban = fetch_ban
    service = _service()

    with caplog.at_level(logging.ERROR):
        asyncio.run(service.record_ban(guild, user))

    assert service.recent_bans[user.id] == "理由なし"
    assert "Failed to fetch ban details" in caplog.text
    assert user.name not in caplog.text


def test_kick_audit_entry_is_saved_without_logging_reason(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(service_module.discord, "User", FakeMember)
    target = FakeMember(500, name="private-member")
    entry = SimpleNamespace(
        action=service_module.discord.AuditLogAction.kick,
        target=target,
        reason="private reason",
    )
    service = _service()

    with caplog.at_level(logging.INFO):
        asyncio.run(service.record_audit_log_entry(entry))

    assert service.recent_kicks[target.id] == "private reason"
    assert "Member kick event recorded" in caplog.text
    assert "private reason" not in caplog.text
    assert target.name not in caplog.text


@pytest.mark.parametrize(
    "entry",
    [
        SimpleNamespace(action="not-kick", target=FakeMember(500), reason=None),
        SimpleNamespace(
            action=service_module.discord.AuditLogAction.kick,
            target=object(),
            reason=None,
        ),
    ],
)
def test_non_kick_or_non_user_audit_entries_are_ignored(
    monkeypatch: pytest.MonkeyPatch,
    entry,
) -> None:
    monkeypatch.setattr(service_module.discord, "User", FakeMember)
    service = _service()

    asyncio.run(service.record_audit_log_entry(entry))

    assert service.recent_kicks == {}
