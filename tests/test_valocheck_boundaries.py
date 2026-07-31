import asyncio
import logging

import pytest

from cogs.valocheck import QuizView, ValoCheckCog
from tests.helpers.discord_fakes import (
    FakeBot,
    FakeGuild,
    FakeInteraction,
    FakeMember,
    FakeRole,
)


def _cog(guild: FakeGuild | None = None) -> ValoCheckCog:
    cog = ValoCheckCog.__new__(ValoCheckCog)
    cog.bot = FakeBot(guild)
    cog.guild_id = guild.id if guild else 100
    cog.sessions = {}
    cog.completed = {}
    cog.questions = [
        {"q": "Q1", "choices": [("A", 0), ("B", 1)]},
        {"q": "Q2", "choices": [("A", 0), ("B", 1)]},
    ]
    cog.max_score = 2
    cog.view_timeout_sec = 90
    cog.role_enjoy_id = 801
    cog.role_gachi_id = 802
    cog.thresh_enjoy_only = 0
    cog.thresh_gachi_only = 2
    cog.label_enjoy = "Enjoy"
    cog.label_gachi = "Gachi"
    cog.label_both = "Both"
    cog.log_channel_id = None
    cog.admin_dm_user_id = None
    return cog


def test_valo_role_initial_response_is_ephemeral_and_session_is_created() -> None:
    guild = FakeGuild(guild_id=100)
    member = FakeMember(500)
    invoker = FakeMember(600)
    interaction = FakeInteraction(invoker, guild=guild)
    cog = _cog(guild)

    async def fake_send_intro(user):
        cog.sessions[user.id]["dm_message"] = "sent"

    cog._send_intro = fake_send_intro

    asyncio.run(
        ValoCheckCog.valo_role.callback(cog, interaction, member, force=False)
    )

    assert interaction.response.calls == [("defer", (), {"ephemeral": True})]
    assert member.id in cog.sessions
    assert cog.sessions[member.id]["idx"] == -1
    assert cog.sessions[member.id]["force_enjoy"] is False
    assert interaction.followup.calls[-1][1]["ephemeral"] is True


def test_last_questions_zero_score_sets_force_enjoy_and_finalizes() -> None:
    member = FakeMember(500)
    interaction = FakeInteraction(member)
    cog = _cog()
    session = {
        "idx": 1,
        "score": 1,
        "answers": [],
        "questions": cog.questions,
    }
    cog.sessions[member.id] = session
    finalized: list[dict] = []

    async def fake_finalize(user, state):
        finalized.append(state.copy())

    cog._finalize = fake_finalize

    asyncio.run(cog.on_answer(interaction, 0, "A"))

    assert finalized[0]["force_enjoy"] is True
    assert finalized[0]["score"] == 1
    assert member.id not in cog.sessions


def test_finalize_removes_old_roles_and_adds_force_enjoy_role() -> None:
    enjoy = FakeRole(801, "Enjoy")
    gachi = FakeRole(802, "Gachi")
    member = FakeMember(500, roles=[enjoy, gachi])
    guild = FakeGuild(guild_id=100, roles=[enjoy, gachi], members=[member])
    cog = _cog(guild)
    cog._save_completed = lambda: None

    async def no_log(*args):
        return None

    cog._log_to_channel = no_log
    state = {
        "score": 2,
        "answers": [],
        "questions": cog.questions,
        "force_enjoy": True,
        "forced": False,
    }

    asyncio.run(cog._finalize(member, state))

    assert member.removed_roles == [(enjoy, gachi)]
    assert member.added_roles == [(enjoy,)]
    assert cog.completed[str(member.id)]["result"] == "Enjoy"
    assert cog.completed[str(member.id)]["force_enjoy"] is True


def test_missing_role_notifies_user_without_mutating_completed_data() -> None:
    member = FakeMember(500)
    guild = FakeGuild(guild_id=100, roles=[], members=[member])
    cog = _cog(guild)
    notices: list[str] = []

    async def capture_notice(title, user_id, state, origin):
        notices.append(title)

    cog._notify_admin_session = capture_notice

    asyncio.run(cog._finalize(member, {"score": 0, "answers": []}))

    assert notices == ["❌ VALO診断: ロールID不正"]
    assert member.sent[0][0] == ("ロールID設定が正しくないみたい。運営に連絡してね。",)
    assert cog.completed == {}


def test_role_api_failure_is_logged_without_member_name(
    caplog: pytest.LogCaptureFixture,
) -> None:
    enjoy = FakeRole(801)
    gachi = FakeRole(802)
    member = FakeMember(500, name="private-member", roles=[gachi])
    member.role_error = RuntimeError("role API unavailable")
    guild = FakeGuild(guild_id=100, roles=[enjoy, gachi], members=[member])
    cog = _cog(guild)

    async def no_notice(*args, **kwargs):
        return None

    cog._notify_admin_session = no_notice

    with caplog.at_level(logging.ERROR):
        asyncio.run(cog._finalize(member, {"score": 0, "answers": []}))

    assert "Failed to update diagnostic roles" in caplog.text
    assert member.name not in caplog.text
    assert cog.completed == {}


def test_command_metadata_permission_check_and_view_timeout_are_stable() -> None:
    cog = _cog()

    async def make_view() -> QuizView:
        return QuizView(cog, user_id=500, timeout_sec=90)

    view = asyncio.run(make_view())

    assert ValoCheckCog.valo_role.name == "valo_role"
    assert (
        ValoCheckCog.valo_role.description
        == "管理者が指定したメンバーにDMで診断を送ります"
    )
    assert len(ValoCheckCog.valo_role.checks) == 1
    assert view.timeout == 90
