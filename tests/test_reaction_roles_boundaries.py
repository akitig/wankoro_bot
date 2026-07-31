import asyncio
import logging
from types import SimpleNamespace

import pytest

from cogs.reaction_roles import GAME_REACTION_ROLES, ReactionRoles
from tests.helpers.discord_fakes import (
    FakeBot,
    FakeEmoji,
    FakeGuild,
    FakeInteraction,
    FakeMember,
    FakePayload,
    FakeRole,
)


def _cog(*, member: FakeMember, role: FakeRole | None = None) -> ReactionRoles:
    guild = FakeGuild(roles=[role] if role else [], members=[member])
    cog = ReactionRoles.__new__(ReactionRoles)
    cog.bot = FakeBot(guild)
    cog.GUILD_ID = guild.id
    cog.REACTION_ROLE_MESSAGE_IDS = {200}
    cog.reaction_role_map = {300: 400}
    return cog


def test_custom_emoji_resolves_role_and_adds_it() -> None:
    role = FakeRole(400)
    member = FakeMember(500)
    cog = _cog(member=member, role=role)

    asyncio.run(cog.handle_reaction(FakePayload(200, 500, FakeEmoji(300)), add=True))

    assert member.added_roles == [(role,)]
    assert member.removed_roles == []


def test_custom_emoji_resolves_role_and_removes_it() -> None:
    role = FakeRole(400)
    member = FakeMember(500, roles=[role])
    cog = _cog(member=member, role=role)

    asyncio.run(cog.handle_reaction(FakePayload(200, 500, FakeEmoji(300)), add=False))

    assert member.removed_roles == [(role,)]


@pytest.mark.parametrize(
    "payload",
    [
        FakePayload(201, 500, FakeEmoji(300)),
        FakePayload(200, 500, FakeEmoji(301)),
        FakePayload(200, 500, FakeEmoji(None)),
    ],
)
def test_unrelated_reaction_does_nothing(payload: FakePayload) -> None:
    member = FakeMember(500)
    cog = _cog(member=member, role=FakeRole(400))

    asyncio.run(cog.handle_reaction(payload))

    assert member.added_roles == []
    assert member.removed_roles == []


def test_missing_role_does_nothing() -> None:
    member = FakeMember(500)
    cog = _cog(member=member)

    asyncio.run(cog.handle_reaction(FakePayload(200, 500, FakeEmoji(300))))

    assert member.added_roles == []


def test_role_permission_error_is_logged_and_propagated(
    caplog: pytest.LogCaptureFixture,
) -> None:
    member = FakeMember(500, name="private-member")
    member.role_error = PermissionError("missing role permission")
    cog = _cog(member=member, role=FakeRole(400))

    with caplog.at_level(logging.ERROR), pytest.raises(PermissionError):
        asyncio.run(cog.handle_reaction(FakePayload(200, 500, FakeEmoji(300))))

    assert "Reaction Role operation failed" in caplog.text
    assert "private-member" not in caplog.text


def test_reaction_role_command_metadata_and_keys_are_stable() -> None:
    assert ReactionRoles.rrcreate.name == "rrcreate"
    assert (
        ReactionRoles.rrcreate.description
        == "よく遊ぶゲームを選ぶリアクションメッセージを作成します"
    )
    assert GAME_REACTION_ROLES["valo"] == ("VALO民", "RR_GAME_VALO")


def test_rrcreate_permission_denial_is_ephemeral() -> None:
    member = FakeMember(500)
    member.guild_permissions = SimpleNamespace(administrator=False)
    interaction = FakeInteraction(member)
    cog = _cog(member=member, role=FakeRole(400))

    asyncio.run(ReactionRoles.rrcreate.callback(cog, interaction))

    assert interaction.response.calls == [
        ("send_message", ("⛔ 管理者のみ実行可",), {"ephemeral": True})
    ]
