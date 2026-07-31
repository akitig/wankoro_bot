import asyncio
import logging

import pytest

import cogs.welcome as welcome_module
from cogs.welcome import Welcome
from tests.helpers.discord_fakes import FakeBot, FakeGuild, FakeMember, FakeRole


class FakeForbidden(Exception):
    pass


def _cog(guild: FakeGuild) -> Welcome:
    cog = Welcome.__new__(Welcome)
    cog.bot = FakeBot(guild)
    cog.user_answers = {}
    cog.processing_users = set()
    cog.GUILD_ID = guild.id
    cog.ADMIN_ID = 700
    cog.ROLE_A = 801
    cog.ROLE_B = 802
    cog.ROLE_C = 803
    cog.WELCOME_CATEGORY_NAME = "welcome"
    cog.LOG_CATEGORY_NAME = "log"
    cog.MANAGER_ROLE_IDS = {900}
    return cog


def test_configured_guild_is_used_and_welcome_messages_are_sent() -> None:
    guild = FakeGuild(guild_id=100)
    member = FakeMember(500, name="NewMember")

    channel = asyncio.run(_cog(guild).create_welcome_room(member))

    assert channel is guild.created_text_channels[0]
    assert guild.created_categories[0].name == "welcome"
    assert channel.name == "welcome-newmember"
    assert len(channel.sent) == 3
    assert member.mention in channel.sent[0][0][0]


def test_staff_role_selects_welcome_staff(monkeypatch: pytest.MonkeyPatch) -> None:
    staff_role = FakeRole(801)
    staff = FakeMember(501, roles=[staff_role])
    guild = FakeGuild(guild_id=100, roles=[staff_role], members=[staff])
    member = FakeMember(500)
    monkeypatch.setattr(welcome_module.random, "choice", lambda values: values[0])
    cog = _cog(guild)

    asyncio.run(cog.create_welcome_room(member))

    assert cog.user_answers[member.id]["staff_id"] == staff.id


def test_missing_staff_roles_falls_back_to_admin_and_still_sends() -> None:
    guild = FakeGuild(guild_id=100)
    member = FakeMember(500)
    cog = _cog(guild)

    channel = asyncio.run(cog.create_welcome_room(member))

    assert cog.user_answers[member.id]["staff_id"] == cog.ADMIN_ID
    assert len(channel.sent) == 3


def test_permission_failure_logs_no_member_name_or_message_body(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(welcome_module.discord, "Forbidden", FakeForbidden)
    guild = FakeGuild(guild_id=100)
    guild.channel_send_error = FakeForbidden("private transport detail")
    member = FakeMember(500, name="private-member-name")

    with caplog.at_level(logging.ERROR):
        channel = asyncio.run(_cog(guild).create_welcome_room(member))

    assert channel is None
    assert "Bot cannot send messages to a welcome channel" in caplog.text
    assert member.name not in caplog.text
    assert member.mention not in caplog.text


def test_welcome_command_metadata_and_ephemeral_permission_denial() -> None:
    guild = FakeGuild(guild_id=100)
    cog = _cog(guild)
    invoking_member = FakeMember(600)
    target = FakeMember(500)

    from tests.helpers.discord_fakes import FakeInteraction

    interaction = FakeInteraction(invoking_member, guild=guild)
    asyncio.run(Welcome.welcome_slash.callback(cog, interaction, target))

    assert Welcome.welcome_slash.name == "welcome"
    assert Welcome.welcome_slash.description == "指定したユーザーのwelcome部屋を作成します"
    assert interaction.response.calls == [
        ("send_message", ("⛔ 管理者のみ実行可",), {"ephemeral": True})
    ]
