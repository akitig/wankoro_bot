import asyncio
import logging

import pytest

from services.reaction_role_service import ReactionRoleService
from tests.helpers.discord_fakes import (
    FakeBot,
    FakeEmoji,
    FakeGuild,
    FakeMember,
    FakePayload,
    FakeRole,
)


def _service(
    *,
    member: FakeMember | None = None,
    role: FakeRole | None = None,
) -> ReactionRoleService:
    guild = FakeGuild(
        guild_id=100,
        members=[member] if member else [],
        roles=[role] if role else [],
    )
    return ReactionRoleService(
        FakeBot(guild),
        guild_id=100,
        message_ids={200},
        reaction_role_map={300: 400},
    )


def test_service_adds_and_removes_resolved_role() -> None:
    role = FakeRole(400)
    member = FakeMember(500)
    service = _service(member=member, role=role)
    payload = FakePayload(200, 500, FakeEmoji(300))

    asyncio.run(service.handle_reaction(payload, add=True))
    asyncio.run(service.handle_reaction(payload, add=False))

    assert member.added_roles == [(role,)]
    assert member.removed_roles == [(role,)]


@pytest.mark.parametrize(
    "payload",
    [
        FakePayload(201, 500, FakeEmoji(300)),
        FakePayload(200, 500, FakeEmoji(301)),
        FakePayload(200, 500, FakeEmoji(None)),
    ],
)
def test_service_ignores_unconfigured_reactions(payload: FakePayload) -> None:
    member = FakeMember(500)
    service = _service(member=member, role=FakeRole(400))

    asyncio.run(service.handle_reaction(payload, add=True))

    assert member.added_roles == []


def test_service_ignores_missing_member_or_role() -> None:
    payload = FakePayload(200, 500, FakeEmoji(300))

    asyncio.run(_service(role=FakeRole(400)).handle_reaction(payload, add=True))
    member = FakeMember(500)
    asyncio.run(_service(member=member).handle_reaction(payload, add=True))

    assert member.added_roles == []


def test_service_logs_and_propagates_role_operation_failure(
    caplog: pytest.LogCaptureFixture,
) -> None:
    member = FakeMember(500, name="private-member")
    member.role_error = PermissionError("missing role permission")
    service = _service(member=member, role=FakeRole(400))

    with caplog.at_level(logging.ERROR), pytest.raises(PermissionError):
        asyncio.run(
            service.handle_reaction(
                FakePayload(200, 500, FakeEmoji(300)),
                add=True,
            )
        )

    assert "Reaction Role operation failed" in caplog.text
    assert member.name not in caplog.text
