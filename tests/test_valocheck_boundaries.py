import asyncio
import logging
from pathlib import Path

import pytest

from cogs.valocheck import QuizView, ValoCheckCog
from services.valocheck_service import ValocheckService
from tests.helpers.discord_fakes import (
    FakeBot,
    FakeGuild,
    FakeInteraction,
    FakeMember,
    FakeRole,
)


def _service(
    guild: FakeGuild | None = None,
    *,
    data_path: Path | None = None,
) -> ValocheckService:
    service = ValocheckService.__new__(ValocheckService)
    service.bot = FakeBot(guild)
    service.guild_id = guild.id if guild else 100
    service.sessions = {}
    service.completed = {}
    service.questions = [
        {"q": "Q1", "choices": [("A", 0), ("B", 1)]},
        {"q": "Q2", "choices": [("A", 0), ("B", 1)]},
    ]
    service.max_score = 2
    service.view_timeout_sec = 90
    service.role_enjoy_id = 801
    service.role_gachi_id = 802
    service.thresh_enjoy_only = 0
    service.thresh_gachi_only = 2
    service.label_enjoy = "Enjoy"
    service.label_gachi = "Gachi"
    service.label_both = "Both"
    service.log_channel_id = None
    service.admin_dm_user_id = None
    service.data_path = data_path or Path("/invalid/test-only.json")
    return service


def test_normal_diagnosis_creates_session() -> None:
    guild = FakeGuild(guild_id=100)
    member = FakeMember(500)
    invoker = FakeMember(600)
    service = _service(guild)

    async def fake_send_intro(user):
        service.sessions[user.id]["dm_message"] = "sent"

    service._send_intro = fake_send_intro

    message = asyncio.run(
        service.diagnose(member, invoked_by=invoker, force=False)
    )

    assert message == f"{member.mention} にDMで診断を送りました。"
    assert service.sessions[member.id]["idx"] == -1
    assert service.sessions[member.id]["force_enjoy"] is False


def test_cog_defers_then_delegates_and_uses_followup() -> None:
    member = FakeMember(500)
    invoker = FakeMember(600)
    interaction = FakeInteraction(invoker)
    calls = []

    class ServiceStub:
        async def diagnose(self, target, *, invoked_by, force):
            calls.append((target, invoked_by, force))
            return "service-result"

    cog = ValoCheckCog.__new__(ValoCheckCog)
    cog.service = ServiceStub()

    asyncio.run(
        ValoCheckCog.valo_role.callback(cog, interaction, member, force=True)
    )

    assert interaction.response.calls == [("defer", (), {"ephemeral": True})]
    assert calls == [(member, invoker, True)]
    assert interaction.followup.calls == [
        (("service-result",), {"ephemeral": True})
    ]


def test_last_questions_zero_score_sets_force_enjoy_and_finalizes() -> None:
    member = FakeMember(500)
    service = _service()
    session = {
        "idx": 1,
        "score": 1,
        "answers": [],
        "questions": service.questions,
    }
    service.sessions[member.id] = session
    finalized: list[dict] = []

    async def fake_finalize(user, state):
        finalized.append(state.copy())

    service._finalize = fake_finalize

    asyncio.run(service.answer(member, 0, "A"))

    assert finalized[0]["force_enjoy"] is True
    assert finalized[0]["score"] == 1
    assert member.id not in service.sessions


def test_finalize_replaces_roles_and_applies_force_enjoy(
    tmp_path: Path,
) -> None:
    enjoy = FakeRole(801, "Enjoy")
    gachi = FakeRole(802, "Gachi")
    member = FakeMember(500, roles=[enjoy, gachi])
    guild = FakeGuild(guild_id=100, roles=[enjoy, gachi], members=[member])
    service = _service(guild, data_path=tmp_path / "completed.json")

    async def no_log(*args):
        return None

    service._log_to_channel = no_log
    state = {
        "score": 2,
        "answers": [],
        "questions": service.questions,
        "force_enjoy": True,
        "forced": False,
    }

    asyncio.run(service._finalize(member, state))

    assert member.removed_roles == [(enjoy, gachi)]
    assert member.added_roles == [(enjoy,)]
    assert service.completed[str(member.id)]["result"] == "Enjoy"
    assert service.completed[str(member.id)]["force_enjoy"] is True


def test_missing_role_notifies_user_without_completed_data() -> None:
    member = FakeMember(500)
    guild = FakeGuild(guild_id=100, roles=[], members=[member])
    service = _service(guild)
    notices: list[str] = []

    async def capture_notice(title, user_id, state, origin):
        notices.append(title)

    service.notify_admin_session = capture_notice

    asyncio.run(service._finalize(member, {"score": 0, "answers": []}))

    assert notices == ["❌ VALO診断: ロールID不正"]
    assert member.sent[0][0] == (
        "ロールID設定が正しくないみたい。運営に連絡してね。",
    )
    assert service.completed == {}


def test_role_api_failure_is_logged_without_member_name(
    caplog: pytest.LogCaptureFixture,
) -> None:
    enjoy = FakeRole(801)
    gachi = FakeRole(802)
    member = FakeMember(500, name="private-member", roles=[gachi])
    member.role_error = RuntimeError("role API unavailable")
    guild = FakeGuild(guild_id=100, roles=[enjoy, gachi], members=[member])
    service = _service(guild)

    async def no_notice(*args, **kwargs):
        return None

    service.notify_admin_session = no_notice

    with caplog.at_level(logging.ERROR):
        asyncio.run(service._finalize(member, {"score": 0, "answers": []}))

    assert "Failed to update diagnostic roles" in caplog.text
    assert member.name not in caplog.text
    assert service.completed == {}


def test_command_metadata_permission_check_and_view_timeout_are_stable() -> None:
    service = _service()

    async def make_view() -> QuizView:
        return QuizView(service, user_id=500, timeout_sec=90)

    view = asyncio.run(make_view())

    assert ValoCheckCog.valo_role.name == "valo_role"
    assert (
        ValoCheckCog.valo_role.description
        == "管理者が指定したメンバーにDMで診断を送ります"
    )
    assert len(ValoCheckCog.valo_role.checks) == 1
    assert view.timeout == 90
