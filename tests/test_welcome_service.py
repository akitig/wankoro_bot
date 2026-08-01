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
    handler_role_id=801,
    inactive_voice_channel_id=None,
    excluded_user_ids=frozenset(),
) -> WelcomeService:
    return WelcomeService(
        FakeBot(guild),
        guild_id=guild.id,
        admin_id=700,
        handler_role_id=handler_role_id,
        inactive_voice_channel_id=inactive_voice_channel_id,
        excluded_user_ids=excluded_user_ids,
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
    in_voice = FakeMember(
        502,
        roles=[role],
        voice=SimpleNamespace(channel=SimpleNamespace(id=1000)),
    )
    guild = FakeGuild(roles=[role], members=[regular, in_voice])

    assert asyncio.run(_service(guild).pick_staff(guild)) is in_voice


def test_only_handler_role_members_are_candidates_and_duplicates_are_removed() -> None:
    handler_role = FakeRole(801)
    other_role = FakeRole(802)
    eligible = FakeMember(501, roles=[handler_role, other_role])
    other = FakeMember(502, roles=[other_role])
    duplicate = eligible
    guild = FakeGuild(
        roles=[handler_role, other_role],
        members=[eligible, other, duplicate],
    )

    service = _service(guild)
    assert service._resolve_handler_candidates(guild) == [eligible]


def test_bots_and_configured_users_are_always_excluded() -> None:
    role = FakeRole(801)
    bot = FakeMember(501, roles=[role], bot=True)
    excluded_active = FakeMember(
        502,
        roles=[role],
        voice=SimpleNamespace(channel=SimpleNamespace(id=1000)),
    )
    excluded_inactive = FakeMember(
        503,
        roles=[role],
        voice=SimpleNamespace(channel=SimpleNamespace(id=900)),
    )
    guild = FakeGuild(roles=[role], members=[bot, excluded_active, excluded_inactive])
    service = _service(
        guild,
        inactive_voice_channel_id=900,
        excluded_user_ids=frozenset({502, 503}),
    )

    assert service._resolve_handler_candidates(guild) == []
    assert asyncio.run(service.pick_staff(guild)) is None


def test_inactive_voice_is_not_prioritized_but_remains_fallback_candidate() -> None:
    role = FakeRole(801)
    inactive = FakeMember(
        501,
        roles=[role],
        voice=SimpleNamespace(channel=SimpleNamespace(id=900)),
    )
    no_voice = FakeMember(502, roles=[role])
    guild = FakeGuild(roles=[role], members=[inactive, no_voice])
    service = _service(guild, inactive_voice_channel_id=900)

    candidates = service._resolve_handler_candidates(guild)
    assert service._resolve_active_voice_candidates(candidates) == []
    assert asyncio.run(service.pick_staff(guild)) is inactive


def test_active_voice_wins_over_inactive_voice() -> None:
    role = FakeRole(801)
    inactive = FakeMember(
        501,
        roles=[role],
        voice=SimpleNamespace(channel=SimpleNamespace(id=900)),
    )
    active = FakeMember(
        502,
        roles=[role],
        voice=SimpleNamespace(channel=SimpleNamespace(id=901)),
    )
    guild = FakeGuild(roles=[role], members=[inactive, active])

    assert (
        asyncio.run(_service(guild, inactive_voice_channel_id=900).pick_staff(guild))
        is active
    )


def test_missing_voice_and_missing_voice_channel_are_safe() -> None:
    role = FakeRole(801)
    missing_voice = FakeMember(501, roles=[role], voice=None)
    missing_channel = FakeMember(
        502,
        roles=[role],
        voice=SimpleNamespace(channel=None),
    )
    guild = FakeGuild(roles=[role], members=[missing_voice, missing_channel])
    service = _service(guild)

    assert service._resolve_active_voice_candidates([missing_voice, missing_channel]) == []


def test_unset_inactive_voice_id_keeps_voice_candidate_eligible() -> None:
    role = FakeRole(801)
    in_voice = FakeMember(
        501,
        roles=[role],
        voice=SimpleNamespace(channel=SimpleNamespace(id=900)),
    )
    guild = FakeGuild(roles=[role], members=[in_voice])

    assert asyncio.run(_service(guild).pick_staff(guild)) is in_voice


def test_previous_handler_is_avoided_when_multiple_candidates_exist() -> None:
    role = FakeRole(801)
    first = FakeMember(501, roles=[role])
    second = FakeMember(502, roles=[role])
    observed = []

    def choose(values):
        observed.append([member.id for member in values])
        return values[0]

    guild = FakeGuild(roles=[role], members=[first, second])
    service = _service(guild, choice=choose)

    assert asyncio.run(service.pick_staff(guild)) is first
    assert asyncio.run(service.pick_staff(guild)) is second
    assert observed == [[501, 502], [502]]
    assert service._last_handler_id == 502


def test_previous_handler_is_avoided_within_active_voice_candidates() -> None:
    role = FakeRole(801)
    first = FakeMember(
        501,
        roles=[role],
        voice=SimpleNamespace(channel=SimpleNamespace(id=1000)),
    )
    second = FakeMember(
        502,
        roles=[role],
        voice=SimpleNamespace(channel=SimpleNamespace(id=1001)),
    )
    not_in_voice = FakeMember(503, roles=[role])
    guild = FakeGuild(roles=[role], members=[first, second, not_in_voice])
    service = _service(guild, choice=lambda values: values[0])

    assert asyncio.run(service.pick_staff(guild)) is first
    assert asyncio.run(service.pick_staff(guild)) is second


def test_single_candidate_can_repeat_in_voice_and_fallback_groups() -> None:
    role = FakeRole(801)
    member = FakeMember(501, roles=[role])
    guild = FakeGuild(roles=[role], members=[member])
    service = _service(guild)

    assert asyncio.run(service.pick_staff(guild)) is member
    assert asyncio.run(service.pick_staff(guild)) is member

    member.voice = SimpleNamespace(channel=SimpleNamespace(id=1000))
    assert asyncio.run(service.pick_staff(guild)) is member


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


def test_excluded_admin_id_remains_emergency_fallback() -> None:
    role = FakeRole(801)
    excluded_admin = FakeMember(700, roles=[role])
    guild = FakeGuild(roles=[role], members=[excluded_admin])
    service = _service(guild, excluded_user_ids=frozenset({700}))

    channel = _create(service, FakeMember(500))

    assert service.get_answers(500)["staff_id"] == 700
    assert "<@700>" in channel.sent[0][0][0]


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
