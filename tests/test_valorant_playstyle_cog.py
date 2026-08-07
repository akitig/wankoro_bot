import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import cogs.valorant_playstyle as playstyle_cog
import main
from services.valorant_playstyle_service import PlaystyleCategory
from tests.helpers.discord_fakes import (
    FakeChannel,
    FakeInteraction,
    FakeMember,
    FakeSentMessage,
)


class BotFake:
    def __init__(self, channel: FakeChannel | None = None) -> None:
        self.channel = channel
        self.cogs: list[object] = []

    def get_channel(self, channel_id: int):
        return self.channel if channel_id == 30 else None

    async def fetch_channel(self, channel_id: int):
        if self.channel is None or channel_id != 30:
            raise LookupError(channel_id)
        return self.channel

    async def add_cog(self, cog: object) -> None:
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
        valo_playstyle_timeout_channel_id=30,
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
        cog, _channel = _make_cog(tmp_path, monkeypatch)
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
        await cog.cog_unload()

    asyncio.run(scenario())


def test_command_reports_dm_failure_without_leaving_session(tmp_path, monkeypatch) -> None:
    class FailingMember(FakeMember):
        async def send(self, *args, **kwargs):
            raise RuntimeError("DM failed")

    async def scenario() -> None:
        cog, _channel = _make_cog(tmp_path, monkeypatch)
        member = FailingMember(3)
        interaction = FakeInteraction(FakeMember(1, name="admin"))

        await cog.valo_role.callback(cog, interaction, member)

        assert member.id not in cog.sessions
        assert "送信に失敗" in interaction.followup.calls[-1][0][0]

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


def test_other_user_cannot_use_diagnosis_views(tmp_path, monkeypatch) -> None:
    async def scenario() -> None:
        cog, _channel = _make_cog(tmp_path, monkeypatch)
        interaction = FakeInteraction(FakeMember(99))
        start = playstyle_cog.StartDiagnosisView(cog, 3)
        question = playstyle_cog.QuestionView(cog, 3, "q01", ["a", "b", "c", "d"])

        assert await start.interaction_check(interaction) is False
        assert await question.interaction_check(interaction) is False
        assert len(interaction.response.calls) == 2

    asyncio.run(scenario())


def test_q15_completion_persists_and_replaces_user_result(tmp_path, monkeypatch) -> None:
    async def scenario() -> None:
        cog, _channel = _make_cog(tmp_path, monkeypatch)
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


def test_save_failure_is_shown_as_failure_and_ends_session(tmp_path, monkeypatch) -> None:
    async def scenario() -> None:
        cog, _channel = _make_cog(tmp_path, monkeypatch)
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

    asyncio.run(scenario())
