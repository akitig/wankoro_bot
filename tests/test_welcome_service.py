import asyncio
import logging
from types import SimpleNamespace

import pytest

import services.welcome_service as service_module
from services.welcome_service import WelcomeService
from tests.helpers.discord_fakes import (
    FakeBot,
    FakeGuild,
    FakeMember,
    FakeRole,
)


class FakeForbidden(Exception):
    pass


def _service(
    guild: FakeGuild,
    *,
    choice=lambda values: values[0],
) -> WelcomeService:
    return WelcomeService(
        FakeBot(guild),
        guild_id=guild.id,
        admin_id=700,
        staff_role_ids=(801, 802, 803),
        choice=choice,
    )


def _create(service: WelcomeService, member: FakeMember):
    return asyncio.run(
        service.create_welcome_room(
            member,
            welcome_embed=lambda: "welcome-embed",
            question_view=lambda: "question-view",
        )
    )


def test_no_staff_candidate_returns_none() -> None:
    guild = FakeGuild()

    assert asyncio.run(_service(guild).pick_staff(guild)) is None


def test_regular_staff_candidate_is_selected() -> None:
    role = FakeRole(801)
    staff = FakeMember(501, roles=[role])
    guild = FakeGuild(roles=[role], members=[staff])

    assert asyncio.run(_service(guild).pick_staff(guild)) is staff


def test_voice_channel_staff_candidate_is_prioritized() -> None:
    role = FakeRole(801)
    regular = FakeMember(501, roles=[role])
    in_voice = FakeMember(502, roles=[role])
    guild = FakeGuild(roles=[role], members=[regular, in_voice])
    guild.voice_channels = [SimpleNamespace(members=[in_voice])]

    assert asyncio.run(_service(guild).pick_staff(guild)) is in_voice


def test_existing_welcome_category_is_reused() -> None:
    category = SimpleNamespace(name="welcome")
    guild = FakeGuild()
    guild.categories = [category]

    channel = _create(_service(guild), FakeMember(500))

    assert guild.created_categories == []
    assert channel.create_kwargs["category"] is category


def test_missing_welcome_category_is_created() -> None:
    guild = FakeGuild()

    _create(_service(guild), FakeMember(500))

    assert [category.name for category in guild.created_categories] == ["welcome"]


def test_duplicate_channel_names_receive_numeric_suffix() -> None:
    guild = FakeGuild()
    guild.channels = [
        SimpleNamespace(name="welcome-newmember"),
        SimpleNamespace(name="welcome-newmember-2"),
    ]

    channel = _create(_service(guild), FakeMember(500, name="NewMember"))

    assert channel.name == "welcome-newmember-3"


def test_permission_overwrites_include_member_bot_and_default_role() -> None:
    guild = FakeGuild()
    member = FakeMember(500)

    channel = _create(_service(guild), member)
    overwrites = channel.create_kwargs["overwrites"]

    assert overwrites[guild.default_role].view_channel is False
    assert overwrites[member].view_channel is True
    assert overwrites[member].send_messages is True
    assert overwrites[guild.me].manage_messages is True
    assert overwrites[guild.me].embed_links is True


def test_staff_gets_permissions_and_is_saved() -> None:
    role = FakeRole(801)
    staff = FakeMember(501, roles=[role])
    guild = FakeGuild(roles=[role], members=[staff])
    service = _service(guild)

    channel = _create(service, FakeMember(500))
    overwrite = channel.create_kwargs["overwrites"][staff]

    assert overwrite.view_channel is True
    assert overwrite.send_messages is True
    assert overwrite.read_message_history is True
    assert service.get_answers(500)["staff_id"] == staff.id


def test_missing_staff_uses_admin_and_sends_three_messages() -> None:
    guild = FakeGuild()
    service = _service(guild)
    member = FakeMember(500)

    channel = _create(service, member)

    assert service.get_answers(member.id) == {"staff_id": 700}
    assert len(channel.sent) == 3
    assert "<@700>" in channel.sent[0][0][0]
    assert channel.sent[1][1]["embed"] == "welcome-embed"
    assert channel.sent[2][1]["view"] == "question-view"


def test_send_forbidden_logs_permissions_and_releases_processing(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(service_module.discord, "Forbidden", FakeForbidden)
    guild = FakeGuild()
    guild.channel_send_error = FakeForbidden("send forbidden")
    service = _service(guild)
    member = FakeMember(500)

    with caplog.at_level(logging.DEBUG):
        channel = _create(service, member)

    assert channel is None
    assert "Bot cannot send messages to a welcome channel" in caplog.text
    assert (
        "Welcome channel permissions: view=True send=True embed=True manage=True"
        in caplog.text
    )
    assert not service.is_processing(member.id)


def test_channel_creation_forbidden_is_logged_and_releases_processing(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(service_module.discord, "Forbidden", FakeForbidden)
    guild = FakeGuild()
    guild.categories = [SimpleNamespace(name="welcome")]
    guild.create_error = FakeForbidden("create forbidden")
    service = _service(guild)
    member = FakeMember(500)

    with caplog.at_level(logging.ERROR):
        channel = _create(service, member)

    assert channel is None
    assert "Missing permission while creating a welcome channel" in caplog.text
    assert not service.is_processing(member.id)


def test_duplicate_workflow_is_skipped(
    caplog: pytest.LogCaptureFixture,
) -> None:
    guild = FakeGuild()
    service = _service(guild)
    member = FakeMember(500)
    service.processing_users.add(member.id)

    with caplog.at_level(logging.WARNING):
        channel = _create(service, member)

    assert channel is None
    assert "Skipped duplicate welcome workflow" in caplog.text


def test_unexpected_failure_still_releases_processing() -> None:
    guild = FakeGuild()
    service = _service(guild)
    member = FakeMember(500)

    def fail_view():
        raise RuntimeError("view construction failed")

    with pytest.raises(RuntimeError, match="view construction failed"):
        asyncio.run(
            service.create_welcome_room(
                member,
                welcome_embed=lambda: "welcome-embed",
                question_view=fail_view,
            )
        )

    assert not service.is_processing(member.id)
