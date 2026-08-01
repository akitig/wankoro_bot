import asyncio
import logging
from types import SimpleNamespace

import pytest

import cogs.welcome as welcome_module
from cogs.welcome import Welcome
from services.welcome_service import WelcomeService
from tests.helpers.discord_fakes import (
    FakeBot,
    FakeChannel,
    FakeGuild,
    FakeInteraction,
    FakeMember,
    FakeRole,
)


class FakeForbidden(Exception):
    pass


def _cog(guild: FakeGuild) -> Welcome:
    cog = Welcome.__new__(Welcome)
    cog.bot = FakeBot(guild)
    cog.GUILD_ID = guild.id
    cog.ADMIN_ID = 700
    cog.WELCOME_CATEGORY_NAME = "welcome"
    cog.LOG_CATEGORY_NAME = "log"
    cog.MANAGER_ROLE_IDS = {900}
    cog.service = WelcomeService(
        cog.bot,
        guild_id=cog.GUILD_ID,
        admin_id=cog.ADMIN_ID,
        handler_role_id=801,
    )
    return cog


def test_configured_guild_is_used_and_welcome_messages_are_sent() -> None:
    guild = FakeGuild(guild_id=100)
    member = FakeMember(500, name="NewMember")

    cog = _cog(guild)
    channel = asyncio.run(
        cog.service.create_welcome_room(
            member,
            welcome_embed=cog.welcome_embed,
            question_view=lambda: object(),
        )
    )

    assert channel is guild.created_text_channels[0]
    assert guild.created_categories[0].name == "welcome"
    assert channel.name == "welcome-newmember"
    assert len(channel.sent) == 3
    assert member.mention in channel.sent[0][0][0]


def test_cog_injects_welcome_handler_config(tmp_path, monkeypatch) -> None:
    captured = {}

    class ServiceFake:
        def __init__(self, bot, **kwargs):
            captured["bot"] = bot
            captured.update(kwargs)

    config = SimpleNamespace(
        guild_id=100,
        admin_id=700,
        welcome_handler_role_id=801,
        welcome_inactive_voice_channel_id=900,
        welcome_handler_excluded_user_ids=frozenset({600}),
        leave_log_channel_id=50,
        manager_role_ids=frozenset({901}),
        require_id=lambda value, _name: value,
    )
    bot = FakeBot(FakeGuild(guild_id=100))
    monkeypatch.setattr(welcome_module, "get_config", lambda: config)
    monkeypatch.setattr(welcome_module, "WelcomeService", ServiceFake)

    Welcome(bot)

    assert captured["handler_role_id"] == 801
    assert captured["inactive_voice_channel_id"] == 900
    assert captured["excluded_user_ids"] == frozenset({600})


def test_missing_handler_role_fails_when_cog_is_created(monkeypatch) -> None:
    config = SimpleNamespace(
        guild_id=100,
        admin_id=700,
        welcome_handler_role_id=None,
        welcome_inactive_voice_channel_id=None,
        welcome_handler_excluded_user_ids=frozenset(),
        leave_log_channel_id=50,
        manager_role_ids=frozenset(),
    )

    def require_id(value, name):
        if value is None:
            raise RuntimeError(f"Missing environment variable: {name}")
        return value

    config.require_id = require_id
    monkeypatch.setattr(welcome_module, "get_config", lambda: config)

    with pytest.raises(RuntimeError, match="WELCOME_HANDLER_ROLE_ID"):
        Welcome(FakeBot(FakeGuild(guild_id=100)))


def test_cog_does_not_duplicate_last_handler_state() -> None:
    cog = _cog(FakeGuild(guild_id=100))

    assert not hasattr(cog, "_last_handler_id")
    assert hasattr(cog.service, "_last_handler_id")


def test_staff_role_selects_welcome_staff(monkeypatch: pytest.MonkeyPatch) -> None:
    staff_role = FakeRole(801)
    staff = FakeMember(501, roles=[staff_role])
    guild = FakeGuild(guild_id=100, roles=[staff_role], members=[staff])
    member = FakeMember(500)
    cog = _cog(guild)
    cog.service._choice = lambda values: values[0]

    asyncio.run(
        cog.service.create_welcome_room(
            member,
            welcome_embed=cog.welcome_embed,
            question_view=lambda: object(),
        )
    )

    assert cog.service.get_answers(member.id)["staff_id"] == staff.id


def test_missing_staff_roles_falls_back_to_admin_and_still_sends() -> None:
    guild = FakeGuild(guild_id=100)
    member = FakeMember(500)
    cog = _cog(guild)

    channel = asyncio.run(
        cog.service.create_welcome_room(
            member,
            welcome_embed=cog.welcome_embed,
            question_view=lambda: object(),
        )
    )

    assert cog.service.get_answers(member.id)["staff_id"] == cog.ADMIN_ID
    assert len(channel.sent) == 3


def test_permission_failure_logs_no_member_name_or_message_body(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    import services.welcome_service as service_module

    monkeypatch.setattr(service_module.discord, "Forbidden", FakeForbidden)
    guild = FakeGuild(guild_id=100)
    guild.channel_send_error = FakeForbidden("private transport detail")
    member = FakeMember(500, name="private-member-name")

    with caplog.at_level(logging.ERROR):
        cog = _cog(guild)
        channel = asyncio.run(
            cog.service.create_welcome_room(
                member,
                welcome_embed=cog.welcome_embed,
                question_view=lambda: object(),
            )
        )

    assert channel is None
    assert "Bot cannot send messages to a welcome channel" in caplog.text
    assert member.name not in caplog.text
    assert member.mention not in caplog.text


def test_welcome_command_metadata_and_ephemeral_permission_denial() -> None:
    guild = FakeGuild(guild_id=100)
    cog = _cog(guild)
    invoking_member = FakeMember(600)
    target = FakeMember(500)

    interaction = FakeInteraction(invoking_member, guild=guild)
    asyncio.run(Welcome.welcome_slash.callback(cog, interaction, target))

    assert Welcome.welcome_slash.name == "welcome"
    assert Welcome.welcome_slash.description == "指定したユーザーのwelcome部屋を作成します"
    assert interaction.response.calls == [
        ("send_message", ("⛔ 管理者のみ実行可",), {"ephemeral": True})
    ]


def test_on_member_join_delegates_to_service() -> None:
    guild = FakeGuild(guild_id=100)
    member = FakeMember(500)
    cog = _cog(guild)
    calls = []

    async def create(target, **kwargs):
        calls.append((target, kwargs))

    cog.service.create_welcome_room = create

    asyncio.run(cog.on_member_join(member))

    assert calls[0][0] is member
    assert callable(calls[0][1]["welcome_embed"])
    assert callable(calls[0][1]["question_view"])


def test_welcome_command_delegates_to_service() -> None:
    guild = FakeGuild(guild_id=100)
    invoker = FakeMember(700)
    member = FakeMember(500)
    interaction = FakeInteraction(invoker, guild=guild)
    cog = _cog(guild)
    channel = FakeChannel()

    async def create(target, **kwargs):
        assert target is member
        return channel

    cog.service.create_welcome_room = create

    asyncio.run(Welcome.welcome_slash.callback(cog, interaction, member))

    assert interaction.response.calls == [
        (
            "send_message",
            (f"✅ {member.display_name} の部屋を作成しました → {channel.mention}",),
            {"ephemeral": False},
        )
    ]


def test_question_view_uses_service_owned_answers() -> None:
    guild = FakeGuild(guild_id=100)
    member = FakeMember(500)
    cog = _cog(guild)
    cog.service.user_answers[member.id] = {"staff_id": 700}
    interaction = FakeInteraction(member)

    async def scenario() -> None:
        view = Welcome.Question2(cog, member)
        await view.set_gender(interaction, "男")

    asyncio.run(scenario())

    assert cog.service.get_answers(member.id)["gender"] == "男"
    assert interaction.response.calls[0][0] == "edit_message"


def test_ok_command_keeps_existing_category_move_behavior() -> None:
    category = SimpleNamespace(name="log")
    guild = FakeGuild(guild_id=100)
    guild.categories = [category]
    invoker = FakeMember(700)
    interaction = FakeInteraction(invoker, guild=guild)
    interaction.channel = FakeChannel()
    cog = _cog(guild)

    asyncio.run(Welcome.ok_slash.callback(cog, interaction))

    assert interaction.channel.edits == [
        {"category": category, "sync_permissions": True}
    ]
    assert interaction.response.calls == [
        (
            "send_message",
            (f"✅ {interaction.channel.mention} を log に移動しました。",),
            {"ephemeral": False},
        )
    ]
