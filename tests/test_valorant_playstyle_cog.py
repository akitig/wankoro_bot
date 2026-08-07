import asyncio
import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import discord
from discord.ext import commands

import cogs.valorant_playstyle as playstyle_cog
import main
from services.valorant_playstyle_service import PlaystyleCategory
from tests.helpers.discord_fakes import (
    FakeChannel,
    FakeGuild,
    FakeInteraction,
    FakeMember,
    FakeSentMessage,
)


class BotFake:
    def __init__(self, channel: FakeChannel | None = None) -> None:
        self.channel = channel
        self.cogs: list[object] = []
        self.source_guild = FakeGuild(guild_id=10)
        self.log_guild = FakeGuild(
            guild_id=20,
            channels=({30: channel} if channel is not None else {}),
        )
        self.users: dict[int, object] = {}

    def get_guild(self, guild_id: int):
        if guild_id == self.source_guild.id:
            return self.source_guild
        if guild_id == self.log_guild.id:
            return self.log_guild
        return None

    def get_user(self, user_id: int):
        return self.users.get(user_id)

    async def fetch_user(self, user_id: int):
        if user_id not in self.users:
            raise LookupError(user_id)
        return self.users[user_id]

    async def add_cog(self, cog: object, **kwargs) -> None:
        cog.add_kwargs = kwargs
        self.cogs.append(cog)


def _config(tmp_path: Path, *, timeout: int = 1800) -> SimpleNamespace:
    return SimpleNamespace(
        valo_playstyle_gachi_min=0.65,
        valo_playstyle_neutral_min=0.35,
        valo_playstyle_gachi_team_min=0.60,
        valo_playstyle_gachi_improvement_min=5 / 9,
        valo_playstyle_gachi_focus_min=5 / 9,
        valo_playstyle_results_path=tmp_path / "results.json",
        valo_playstyle_timeout_seconds=timeout,
        guild_id=10,
        valo_playstyle_log_guild_id=20,
        valo_playstyle_log_channel_id=30,
        valo_playstyle_resend_user_id=40,
        require_id=lambda value, _name: value,
    )


def _make_cog(tmp_path: Path, monkeypatch, *, timeout: int = 1800):
    monkeypatch.setattr(
        playstyle_cog,
        "get_config",
        lambda: _config(tmp_path, timeout=timeout),
    )
    channel = FakeChannel()
    return playstyle_cog.ValorantPlaystyleCog(BotFake(channel)), channel


def _maximum_answers(cog: playstyle_cog.ValorantPlaystyleCog) -> dict[str, str]:
    primary = set(cog.core.classification_policy.weights)
    return {
        question.id: max(
            question.choices,
            key=lambda choice: sum(choice.scores.get(axis, 0) for axis in primary),
        ).id
        for question in cog.core.question_set.questions
    }


def test_cog_uses_configured_policy_and_registers_command(tmp_path, monkeypatch) -> None:
    cog, _channel = _make_cog(tmp_path, monkeypatch)

    assert cog.core.classification_policy.gachi_minimum == 0.65
    assert cog.core.classification_policy.neutral_minimum == 0.35
    assert cog.valo_role.name == "valo_role"
    assert cog.valo_role.default_permissions.administrator is True
    log_cog = playstyle_cog.ValorantPlaystyleLogCog(cog)
    assert log_cog.valo_role_log.name == "valo_role_log"
    assert log_cog.valo_role_log.default_permissions.administrator is True
    assert "cogs.valorant_playstyle" in main.COGS


def test_cog_load_re_evaluates_saved_results(tmp_path, monkeypatch) -> None:
    async def scenario() -> None:
        cog, _channel = _make_cog(tmp_path, monkeypatch)
        cog.results.repository.load = Mock()
        cog.results.reevaluate_all = AsyncMock(return_value=())

        await cog.cog_load()

        cog.results.repository.load.assert_called_once_with()
        cog.results.reevaluate_all.assert_awaited_once_with("2.0")

    asyncio.run(scenario())


def test_command_rejects_bot_and_duplicate_session(tmp_path, monkeypatch) -> None:
    async def scenario() -> None:
        cog, channel = _make_cog(tmp_path, monkeypatch)
        admin = FakeMember(1, name="admin")
        bot_member = FakeMember(2, bot=True)
        interaction = FakeInteraction(admin)
        await cog.valo_role.callback(cog, interaction, bot_member)
        assert "Bot" in interaction.followup.calls[-1][0][0]

        member = FakeMember(3)
        first = FakeInteraction(admin)
        await cog.valo_role.callback(cog, first, member)
        second = FakeInteraction(admin)
        await cog.valo_role.callback(cog, second, member)
        assert "現在診断中" in second.followup.calls[-1][0][0]
        assert len(member.sent) == 1
        audit = channel.sent[-1][1]["embed"]
        assert audit.title == "🐶 VALORANT診断を送信しました"
        assert member.mention in audit.description
        assert "<@1>" in audit.description
        assert "User ID：3" in audit.description
        assert "送信者ID：1" in audit.description
        assert "診断開始待ち" in audit.description
        await cog.cog_unload()

    asyncio.run(scenario())


def test_command_reports_dm_failure_without_leaving_session(tmp_path, monkeypatch) -> None:
    class FailingMember(FakeMember):
        async def send(self, *args, **kwargs):
            raise RuntimeError("DM failed")

    async def scenario() -> None:
        cog, channel = _make_cog(tmp_path, monkeypatch)
        member = FailingMember(3)
        interaction = FakeInteraction(FakeMember(1, name="admin"))

        await cog.valo_role.callback(cog, interaction, member)

        assert member.id not in cog.sessions
        assert "送信に失敗" in interaction.followup.calls[-1][0][0]
        audit = channel.sent[-1][1]["embed"]
        assert "送信に失敗" in audit.title
        assert member.mention in audit.description
        assert "<@1>" in audit.description
        assert "User ID：3" in audit.description
        assert "送信者ID：1" in audit.description

    asyncio.run(scenario())


def test_start_and_question_choice_shuffle_preserve_choice_ids(
    tmp_path, monkeypatch
) -> None:
    async def scenario() -> None:
        cog, _channel = _make_cog(tmp_path, monkeypatch)
        member = FakeMember(3)
        session = playstyle_cog.DiagnosisSession(member, 1, "admin")
        session.dm_message = FakeSentMessage()
        cog.sessions[member.id] = session
        monkeypatch.setattr(
            playstyle_cog.random,
            "sample",
            lambda values, k: list(reversed(values)),
        )

        await cog.start_questions(member.id)

        edit = session.dm_message.edits[-1]
        view = edit["view"]
        assert "Q1 / 15" in edit["embed"].description
        assert [button.choice_id for button in view.children] == ["d", "c", "b", "a"]
        assert [button.label for button in view.children] == ["1", "2", "3", "4"]
        await cog.cog_unload()

    asyncio.run(scenario())


def test_start_and_each_answer_reset_idle_timeout(tmp_path, monkeypatch) -> None:
    async def scenario() -> None:
        cog, _channel = _make_cog(tmp_path, monkeypatch)
        member = FakeMember(3)
        session = playstyle_cog.DiagnosisSession(member, 1, "admin")
        session.dm_message = FakeSentMessage()
        cog.sessions[member.id] = session
        reset = Mock()
        monkeypatch.setattr(cog, "_reset_timeout", reset)

        await cog.start_questions(member.id)
        await cog.answer_question(member.id, "q01", "a")

        assert reset.call_count == 2

    asyncio.run(scenario())


def test_individual_answers_do_not_emit_audit_logs(tmp_path, monkeypatch) -> None:
    async def scenario() -> None:
        cog, channel = _make_cog(tmp_path, monkeypatch)
        member = FakeMember(3)
        session = playstyle_cog.DiagnosisSession(member, 1, "admin")
        session.dm_message = FakeSentMessage()
        session.question_index = 0
        cog.sessions[member.id] = session

        await cog.answer_question(member.id, "q01", "a")

        assert channel.sent == []
        await cog.cog_unload()

    asyncio.run(scenario())


def test_other_user_cannot_use_diagnosis_views(tmp_path, monkeypatch) -> None:
    async def scenario() -> None:
        cog, channel = _make_cog(tmp_path, monkeypatch)
        interaction = FakeInteraction(FakeMember(99))
        start = playstyle_cog.StartDiagnosisView(cog, 3)
        question = playstyle_cog.QuestionView(cog, 3, "q01", ["a", "b", "c", "d"])

        assert await start.interaction_check(interaction) is False
        assert await question.interaction_check(interaction) is False
        assert len(interaction.response.calls) == 2

    asyncio.run(scenario())


def test_q15_completion_persists_and_replaces_user_result(tmp_path, monkeypatch) -> None:
    async def scenario() -> None:
        cog, channel = _make_cog(tmp_path, monkeypatch)
        await cog.cog_load()
        member = FakeMember(3)
        session = playstyle_cog.DiagnosisSession(member, 1, "admin")
        session.dm_message = FakeSentMessage()
        session.question_index = 14
        answers = _maximum_answers(cog)
        session.answers = dict(list(answers.items())[:-1])
        cog.sessions[member.id] = session

        await cog.answer_question(member.id, "q15", answers["q15"])

        saved = cog.results.repository.get_result(member.id)
        assert saved is not None
        assert saved["answers"] == answers
        assert saved["category"] == PlaystyleCategory.GACHI.value
        assert member.id not in cog.sessions
        assert session.dm_message.edits[-1]["view"] is None
        completion = channel.sent[-1][1]["embed"]
        dm_result = session.dm_message.edits[-1]["embed"].description
        assert completion.title == "🐶 VALORANT診断が完了しました"
        assert member.mention in completion.description
        assert "<@1>" in completion.description
        assert "User ID：3" in completion.description
        assert "送信者ID：1" in completion.description
        assert "総合スコア：100%" in completion.description
        assert dm_result in completion.description.replace("総合スコア：100%\n\n", "")

        session = playstyle_cog.DiagnosisSession(member, 2, "second-admin")
        session.dm_message = FakeSentMessage()
        session.question_index = 14
        session.answers = dict(list(answers.items())[:-1])
        cog.sessions[member.id] = session
        await cog.answer_question(member.id, "q15", answers["q15"])
        replaced = cog.results.repository.get_result(member.id)
        assert replaced is not None
        assert replaced["invoked_by"] == 2

    asyncio.run(scenario())


def test_audit_send_failure_does_not_break_diagnosis_start(
    tmp_path, monkeypatch
) -> None:
    async def scenario() -> None:
        monkeypatch.setattr(playstyle_cog, "get_config", lambda: _config(tmp_path))
        channel = FakeChannel(send_error=RuntimeError("audit unavailable"))
        cog = playstyle_cog.ValorantPlaystyleCog(BotFake(channel))
        member = FakeMember(3)
        interaction = FakeInteraction(FakeMember(1, name="admin"))

        await cog.valo_role.callback(cog, interaction, member)

        assert member.id in cog.sessions
        assert "診断を送信しました" in interaction.followup.calls[-1][0][0]
        await cog.cog_unload()

    asyncio.run(scenario())


def test_completion_audit_failure_does_not_lose_saved_result(
    tmp_path, monkeypatch
) -> None:
    async def scenario() -> None:
        monkeypatch.setattr(playstyle_cog, "get_config", lambda: _config(tmp_path))
        channel = FakeChannel(send_error=RuntimeError("audit unavailable"))
        cog = playstyle_cog.ValorantPlaystyleCog(BotFake(channel))
        await cog.cog_load()
        member = FakeMember(3)
        session = playstyle_cog.DiagnosisSession(member, 1, "admin")
        session.dm_message = FakeSentMessage()
        session.answers = _maximum_answers(cog)
        cog.sessions[member.id] = session

        await cog._complete(session)

        assert cog.results.repository.get_result(member.id) is not None
        assert member.id not in cog.sessions
        assert "診断結果" in session.dm_message.edits[-1]["embed"].title

    asyncio.run(scenario())


def test_audit_uses_configured_guild_and_rejects_channel_guild_mismatch(
    tmp_path, monkeypatch
) -> None:
    async def scenario() -> None:
        cog, channel = _make_cog(tmp_path, monkeypatch)
        channel.guild = cog.bot.source_guild

        sent = await cog._send_audit(discord.Embed(title="test"), context="test")

        assert sent is False
        assert channel.sent == []

    asyncio.run(scenario())


def test_audit_does_not_use_same_channel_id_from_diagnosis_guild(
    tmp_path, monkeypatch
) -> None:
    async def scenario() -> None:
        cog, management_channel = _make_cog(tmp_path, monkeypatch)
        diagnosis_channel = FakeChannel()
        diagnosis_channel.guild = cog.bot.source_guild
        cog.bot.source_guild._channels[30] = diagnosis_channel

        sent = await cog._send_audit(discord.Embed(title="test"), context="test")

        assert sent is True
        assert diagnosis_channel.sent == []
        assert len(management_channel.sent) == 1

    asyncio.run(scenario())


def test_startup_validation_checks_both_guilds_and_log_permissions(
    tmp_path, monkeypatch, caplog
) -> None:
    cog, _channel = _make_cog(tmp_path, monkeypatch)
    caplog.set_level(logging.INFO)

    cog._validate_cross_guild_setup()

    assert "cross-guild setup validated" in caplog.text

    cog.bot.log_guild._channels.clear()
    cog._validate_cross_guild_setup()
    assert "log channel is unavailable" in caplog.text


def test_startup_validation_reports_missing_diagnosis_and_log_guilds(
    tmp_path, monkeypatch, caplog
) -> None:
    cog, _channel = _make_cog(tmp_path, monkeypatch)
    caplog.set_level(logging.ERROR)
    cog.bot.get_guild = Mock(return_value=None)

    cog._validate_cross_guild_setup()

    assert "diagnosis guild is unavailable" in caplog.text
    assert "log guild is unavailable" in caplog.text


def test_answer_log_rejects_wrong_channel_before_lookup(tmp_path, monkeypatch) -> None:
    async def scenario() -> None:
        cog, _channel = _make_cog(tmp_path, monkeypatch)
        cog.results.repository.get_result = Mock(side_effect=AssertionError("lookup"))
        interaction = FakeInteraction(
            FakeMember(1), guild=cog.bot.log_guild, channel_id=999
        )
        log_cog = playstyle_cog.ValorantPlaystyleLogCog(cog)

        await log_cog.valo_role_log.callback(
            log_cog, interaction, user=FakeMember(3), user_id=None
        )

        response = interaction.response.calls[-1]
        assert "ログチャンネルでのみ" in response[1][0]
        assert response[2]["ephemeral"] is True

    asyncio.run(scenario())


def test_answer_log_rejects_wrong_guild_and_non_admin_before_lookup(
    tmp_path, monkeypatch
) -> None:
    async def scenario() -> None:
        cog, _channel = _make_cog(tmp_path, monkeypatch)
        cog.results.repository.get_result = Mock(side_effect=AssertionError("lookup"))
        log_cog = playstyle_cog.ValorantPlaystyleLogCog(cog)
        wrong_guild = FakeInteraction(
            FakeMember(1), guild=cog.bot.source_guild, channel_id=30
        )
        await log_cog.valo_role_log.callback(
            log_cog, wrong_guild, user=None, user_id="3"
        )
        assert "管理サーバー" in wrong_guild.response.calls[-1][1][0]

        non_admin = FakeInteraction(
            FakeMember(1, administrator=False),
            guild=cog.bot.log_guild,
            channel_id=30,
        )
        await log_cog.valo_role_log.callback(
            log_cog, non_admin, user=None, user_id="3"
        )
        assert "管理者のみ" in non_admin.response.calls[-1][1][0]
        assert non_admin.response.calls[-1][2]["ephemeral"] is True

    asyncio.run(scenario())


def test_answer_log_validates_exclusive_user_parameters(tmp_path, monkeypatch) -> None:
    async def scenario() -> None:
        cog, _channel = _make_cog(tmp_path, monkeypatch)
        cog.results.repository.get_result = Mock(side_effect=AssertionError("lookup"))
        log_cog = playstyle_cog.ValorantPlaystyleLogCog(cog)

        both = FakeInteraction(FakeMember(1), guild=cog.bot.log_guild, channel_id=30)
        await log_cog.valo_role_log.callback(
            log_cog, both, user=FakeMember(3), user_id="3"
        )
        assert "どちらか一方" in both.response.calls[-1][1][0]

        neither = FakeInteraction(
            FakeMember(1), guild=cog.bot.log_guild, channel_id=30
        )
        await log_cog.valo_role_log.callback(
            log_cog, neither, user=None, user_id=None
        )
        assert "user または user_id" in neither.response.calls[-1][1][0]

        for invalid in ("", "abc", " 3", "0", "-1", str(1 << 64), "１２３"):
            interaction = FakeInteraction(
                FakeMember(1), guild=cog.bot.log_guild, channel_id=30
            )
            await log_cog.valo_role_log.callback(
                log_cog, interaction, user=None, user_id=invalid
            )
            assert "User IDが正しくありません" in interaction.response.calls[-1][1][0]

    asyncio.run(scenario())


def test_answer_log_reports_missing_result_ephemerally(tmp_path, monkeypatch) -> None:
    async def scenario() -> None:
        cog, _channel = _make_cog(tmp_path, monkeypatch)
        await cog.cog_load()
        interaction = FakeInteraction(
            FakeMember(1), guild=cog.bot.log_guild, channel_id=30
        )
        log_cog = playstyle_cog.ValorantPlaystyleLogCog(cog)

        await log_cog.valo_role_log.callback(
            log_cog, interaction, user=None, user_id="3"
        )

        assert interaction.response.calls[-1] == ("defer", (), {"ephemeral": True})
        args, kwargs = interaction.followup.calls[-1]
        assert "診断結果はまだありません" in args[0]
        assert kwargs["ephemeral"] is True

        member_interaction = FakeInteraction(
            FakeMember(1), guild=cog.bot.log_guild, channel_id=30
        )
        await log_cog.valo_role_log.callback(
            log_cog,
            member_interaction,
            user=FakeMember(4),
            user_id=None,
        )
        assert "診断結果はまだありません" in member_interaction.followup.calls[-1][0][0]

    asyncio.run(scenario())


def test_answer_log_restores_saved_answers_as_ephemeral_pages(
    tmp_path, monkeypatch
) -> None:
    async def scenario() -> None:
        cog, channel = _make_cog(tmp_path, monkeypatch)
        await cog.cog_load()
        answers = {question.id: "c" for question in cog.core.question_set.questions}
        classification = cog.core.classify_complete(answers)
        await cog.results.save_completed(
            user_id=3,
            answers=answers,
            classification=classification,
            diagnosis_version=cog.core.question_set.diagnosis_version,
            invoked_by=1,
            invoked_by_name="admin",
        )
        interaction = FakeInteraction(
            FakeMember(9), guild=cog.bot.log_guild, channel_id=30
        )
        source_member = FakeMember(3, name="source-member")
        source_member.guild = cog.bot.source_guild
        cog.bot.source_guild.members.append(source_member)
        cog.bot.users[3] = FakeMember(3, name="cached-user")
        log_cog = playstyle_cog.ValorantPlaystyleLogCog(cog)

        await log_cog.valo_role_log.callback(
            log_cog, interaction, user=None, user_id="3"
        )

        assert len(interaction.followup.calls) == 4
        assert all(call[1]["ephemeral"] is True for call in interaction.followup.calls)
        summary = interaction.followup.calls[0][1]["embed"].description
        assert "対象：source-member (<@3>)" in summary
        assert "対象User ID：3" in summary
        assert "診断日時：" in summary
        assert "最終評価日時：" in summary
        assert "送信者：admin (<@1>)" in summary
        assert "送信者ID：1" in summary
        assert "総合スコア：" in summary
        assert "勝利志向" in summary
        assert "フィードバック傾向" in summary
        rendered = "\n".join(
            call[1]["embed"].description for call in interaction.followup.calls[1:]
        )
        assert rendered.index("**Q1**") < rendered.index("**Q15**")
        for question in cog.core.question_set.questions:
            selected = next(choice for choice in question.choices if choice.id == "c")
            assert question.text in rendered
            assert selected.text in rendered

        member_interaction = FakeInteraction(
            FakeMember(9), guild=cog.bot.log_guild, channel_id=30
        )
        await log_cog.valo_role_log.callback(
            log_cog,
            member_interaction,
            user=FakeMember(3, name="management-member"),
            user_id=None,
        )
        assert len(member_interaction.followup.calls) == 4
        assert all(
            call[1]["ephemeral"] is True
            for call in member_interaction.followup.calls
        )
        assert channel.sent == []

    asyncio.run(scenario())


def test_answer_log_version_mismatch_does_not_restore_or_delete_result(
    tmp_path, monkeypatch
) -> None:
    async def scenario() -> None:
        cog, _channel = _make_cog(tmp_path, monkeypatch)
        await cog.cog_load()
        answers = _maximum_answers(cog)
        classification = cog.core.classify_complete(answers)
        await cog.results.save_completed(
            user_id=3,
            answers=answers,
            classification=classification,
            diagnosis_version="older-version",
            invoked_by=1,
            invoked_by_name="admin",
        )
        before = cog.results.repository.get_result(3)
        interaction = FakeInteraction(
            FakeMember(9), guild=cog.bot.log_guild, channel_id=30
        )
        log_cog = playstyle_cog.ValorantPlaystyleLogCog(cog)

        await log_cog.valo_role_log.callback(
            log_cog, interaction, user=None, user_id="3"
        )

        assert len(interaction.followup.calls) == 1
        embed = interaction.followup.calls[0][1]["embed"]
        assert "安全に復元できない" in embed.description
        assert "older-version" in embed.description
        assert cog.results.repository.get_result(3) == before

    asyncio.run(scenario())


def test_save_failure_is_shown_as_failure_and_ends_session(tmp_path, monkeypatch) -> None:
    async def scenario() -> None:
        cog, channel = _make_cog(tmp_path, monkeypatch)
        member = FakeMember(3)
        session = playstyle_cog.DiagnosisSession(member, 1, "admin")
        session.dm_message = FakeSentMessage()
        session.answers = _maximum_answers(cog)
        cog.sessions[member.id] = session
        cog.results.save_completed = AsyncMock(side_effect=OSError("disk full"))

        await cog._complete(session)

        embed = session.dm_message.edits[-1]["embed"]
        assert "保存できませんでした" in embed.title
        assert member.id not in cog.sessions
        assert "保存に失敗" in channel.sent[-1][1]["embed"].title

    asyncio.run(scenario())


def test_timeout_notifies_and_preserves_previous_result(tmp_path, monkeypatch) -> None:
    async def scenario() -> None:
        cog, channel = _make_cog(tmp_path, monkeypatch)
        await cog.cog_load()
        answers = _maximum_answers(cog)
        classification = cog.core.classify_complete(answers)
        await cog.results.save_completed(
            user_id=3,
            answers=answers,
            classification=classification,
            diagnosis_version="2.0",
            invoked_by=1,
            invoked_by_name="admin",
        )
        old = cog.results.repository.get_result(3)
        member = FakeMember(3)
        session = playstyle_cog.DiagnosisSession(member, 1, "admin")
        session.dm_message = FakeSentMessage()
        session.answers = {"q01": "a"}
        cog.sessions[member.id] = session

        await cog._expire(session)

        assert cog.results.repository.get_result(3) == old
        assert member.id not in cog.sessions
        assert "30分" in session.dm_message.edits[-1]["embed"].description
        notification = channel.sent[-1][1]["embed"].description
        assert "1 / 15" in notification
        assert "<@1>" in notification
        assert "<@40>" in notification
        assert "User ID：3" in notification
        assert "送信者ID：1" in notification

    asyncio.run(scenario())


def test_timeout_generation_prevents_old_task_from_expiring_session(
    tmp_path, monkeypatch
) -> None:
    async def scenario() -> None:
        cog, _channel = _make_cog(tmp_path, monkeypatch, timeout=0.001)
        member = FakeMember(3)
        session = playstyle_cog.DiagnosisSession(member, 1, "admin")
        session.dm_message = FakeSentMessage()
        cog.sessions[member.id] = session
        session.timeout_generation = 2

        await cog._timeout_after(member.id, 1)

        assert member.id in cog.sessions

    asyncio.run(scenario())


def test_setup_adds_cog(tmp_path, monkeypatch) -> None:
    async def scenario() -> None:
        monkeypatch.setattr(playstyle_cog, "get_config", lambda: _config(tmp_path))
        bot = BotFake()
        await playstyle_cog.setup(bot)
        assert isinstance(bot.cogs[0], playstyle_cog.ValorantPlaystyleCog)
        assert isinstance(bot.cogs[1], playstyle_cog.ValorantPlaystyleLogCog)
        assert bot.cogs[1].add_kwargs["guild"].id == 20

    asyncio.run(scenario())


def test_commands_are_scoped_to_separate_guilds(tmp_path, monkeypatch) -> None:
    async def scenario() -> None:
        monkeypatch.setattr(playstyle_cog, "get_config", lambda: _config(tmp_path))
        bot = commands.Bot(command_prefix="/", intents=discord.Intents.none())
        await playstyle_cog.setup(bot)
        source = discord.Object(id=10)
        management = discord.Object(id=20)
        bot.tree.copy_global_to(guild=source)

        assert {command.name for command in bot.tree.get_commands(guild=source)} == {
            "valo_role"
        }
        assert {
            command.name for command in bot.tree.get_commands(guild=management)
        } == {"valo_role_log"}
        assert {command.name for command in bot.tree.get_commands()} == {"valo_role"}
        assert bot.tree.get_commands(guild=discord.Object(id=30)) == []
        await bot.close()

    asyncio.run(scenario())
