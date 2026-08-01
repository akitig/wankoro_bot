import asyncio
from pathlib import Path
from types import SimpleNamespace

import discord
import pytest

import cogs.availability_poll as poll_cog
import main


class ServiceFake:
    def __init__(self, **kwargs) -> None:
        self.calls = []

    def poll_id_from_message(self, _message):
        return "poll"

    async def handle_answer(self, interaction, answer, poll_id):
        self.calls.append(("answer", interaction, answer, poll_id))

    async def initialize(self):
        self.calls.append(("initialize",))

    async def shutdown(self):
        self.calls.append(("shutdown",))

    async def skip_next(self, interaction):
        self.calls.append(("skip", interaction))

    async def stop(self, interaction):
        self.calls.append(("stop", interaction))

    async def resume(self, interaction):
        self.calls.append(("resume", interaction))


class BotFake:
    def __init__(self) -> None:
        self.views = []
        self.cogs = []

    def add_view(self, view):
        self.views.append(view)

    async def add_cog(self, cog):
        self.cogs.append(cog)


def fake_config(tmp_path: Path):
    return SimpleNamespace(
        availability_poll_channel_id=10,
        availability_poll_timezone="Asia/Tokyo",
        availability_poll_weekday_windows=("20:00-21:00",),
        availability_poll_holiday_windows=("13:00-14:00", "20:00-21:00"),
        availability_poll_state_path=tmp_path / "poll.json",
        availability_poll_audit_guild_id=30,
        availability_poll_audit_channel_id=40,
        require_id=lambda value, _name: value,
    )


def make_cog(tmp_path, monkeypatch):
    monkeypatch.setattr(poll_cog, "get_config", lambda: fake_config(tmp_path))
    monkeypatch.setattr(poll_cog, "AvailabilityPollService", ServiceFake)
    bot = BotFake()
    return poll_cog.AvailabilityPollCog(bot), bot


def test_view_metadata_and_disabled_state() -> None:
    async def scenario():
        service = ServiceFake()
        view = poll_cog.AvailabilityPollView(service, poll_id=None, disabled=False)
        disabled = poll_cog.AvailabilityPollView(service, poll_id="poll", disabled=True)
        assert view.timeout is None
        assert [item.label for item in view.children] == [
            "🎯 VALORANT",
            "🎮 その他ゲーム",
            "🗣️ 作業VC",
            "✖ 取り消す",
        ]
        assert [item.custom_id for item in view.children] == [
            "availability_poll:valorant",
            "availability_poll:other_game",
            "availability_poll:work_vc",
            "availability_poll:cancel",
        ]
        assert [item.style for item in view.children[:3]] == [
            discord.ButtonStyle.primary,
        ] * 3
        assert view.children[3].style is discord.ButtonStyle.secondary
        assert all(item.disabled for item in disabled.children)

    asyncio.run(scenario())


def test_button_callbacks_delegate() -> None:
    async def scenario():
        service = ServiceFake()
        view = poll_cog.AvailabilityPollView(service, poll_id=None, disabled=False)
        interaction = SimpleNamespace(message=object())
        for item in view.children:
            await item.callback(interaction)
        assert [call[2] for call in service.calls] == [
            "valorant",
            "other_game",
            "work_vc",
            None,
        ]
        assert all(call[3] == "poll" for call in service.calls)

    asyncio.run(scenario())


def test_cog_lifecycle_commands_and_registration(tmp_path, monkeypatch) -> None:
    async def scenario():
        cog, bot = make_cog(tmp_path, monkeypatch)
        interaction = object()
        await cog.cog_load()
        await cog.availability_poll_skip_next.callback(cog, interaction)
        await cog.availability_poll_stop.callback(cog, interaction)
        await cog.availability_poll_resume.callback(cog, interaction)
        await cog.cog_unload()
        assert len(bot.views) == 1
        assert cog.service.calls == [
            ("initialize",),
            ("skip", interaction),
            ("stop", interaction),
            ("resume", interaction),
            ("shutdown",),
        ]

    asyncio.run(scenario())
    assert "cogs.availability_poll" in main.COGS


def test_slash_command_metadata_and_permissions(tmp_path, monkeypatch) -> None:
    cog, _bot = make_cog(tmp_path, monkeypatch)
    commands = {
        cog.availability_poll_skip_next.name: cog.availability_poll_skip_next,
        cog.availability_poll_stop.name: cog.availability_poll_stop,
        cog.availability_poll_resume.name: cog.availability_poll_resume,
    }
    assert set(commands) == {
        "availability_poll_skip_next",
        "availability_poll_stop",
        "availability_poll_resume",
    }
    assert all(command.default_permissions.administrator for command in commands.values())


def test_setup_is_callable() -> None:
    assert callable(poll_cog.setup)


@pytest.mark.parametrize(
    ("field", "environment_name"),
    [
        ("availability_poll_channel_id", "AVAILABILITY_POLL_CHANNEL_ID"),
        ("availability_poll_audit_guild_id", "AVAILABILITY_POLL_AUDIT_GUILD_ID"),
        ("availability_poll_audit_channel_id", "AVAILABILITY_POLL_AUDIT_CHANNEL_ID"),
    ],
)
def test_required_ids_are_validated_when_cog_is_created(
    tmp_path,
    monkeypatch,
    field,
    environment_name,
) -> None:
    value = fake_config(tmp_path)
    setattr(value, field, None)

    def require_id(item, name):
        if item is None:
            raise RuntimeError(f"Missing environment variable: {name}")
        return item

    value.require_id = require_id
    monkeypatch.setattr(poll_cog, "get_config", lambda: value)
    with pytest.raises(RuntimeError, match=environment_name):
        poll_cog.AvailabilityPollCog(BotFake())
