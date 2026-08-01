import asyncio
from pathlib import Path
from types import SimpleNamespace

import discord

import cogs.bump_panel as bump_cog
import main


class ServiceFake:
    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs
        self.calls: list[tuple[object, ...]] = []

    async def initialize(self) -> None:
        self.calls.append(("initialize",))

    async def shutdown(self) -> None:
        self.calls.append(("shutdown",))

    async def ensure_panel(self) -> None:
        self.calls.append(("ensure_panel",))

    async def handle_message(self, message: object) -> None:
        self.calls.append(("handle_message", message))

    async def send_command_guide(self, interaction: object) -> None:
        self.calls.append(("send_command_guide", interaction))


class BotFake:
    def __init__(self) -> None:
        self.views: list[discord.ui.View] = []
        self.cogs: list[object] = []

    def add_view(self, view: discord.ui.View) -> None:
        self.views.append(view)

    async def add_cog(self, cog: object) -> None:
        self.cogs.append(cog)


def config(tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(
        bump_channel_id=10,
        disboard_bot_id=20,
        disboard_bump_command_id=30,
        bump_cooldown_seconds=7200,
        bump_panel_state_path=tmp_path / "bump.json",
        require_id=lambda value, _name: value,
    )


def make_cog(tmp_path: Path, monkeypatch) -> tuple[bump_cog.BumpPanelCog, BotFake]:
    monkeypatch.setattr(bump_cog, "get_config", lambda: config(tmp_path))
    monkeypatch.setattr(bump_cog, "BumpPanelService", ServiceFake)
    bot = BotFake()
    return bump_cog.BumpPanelCog(bot), bot


def test_view_metadata_for_available_and_waiting_states() -> None:
    async def scenario() -> None:
        service = ServiceFake()

        available = bump_cog.BumpPanelView(service, available=True)
        waiting = bump_cog.BumpPanelView(service, available=False)

        assert available.timeout is None
        assert waiting.timeout is None
        available_button = available.children[0]
        waiting_button = waiting.children[0]
        assert available_button.custom_id == "bump_panel:open_command"
        assert available_button.label == "BUMPする"
        assert available_button.style is discord.ButtonStyle.success
        assert available_button.disabled is False
        assert waiting_button.custom_id == "bump_panel:open_command"
        assert waiting_button.label == "BUMP待機中"
        assert waiting_button.style is discord.ButtonStyle.secondary
        assert waiting_button.disabled is True

    asyncio.run(scenario())


def test_button_callback_delegates_to_service() -> None:
    async def scenario() -> None:
        service = ServiceFake()
        view = bump_cog.BumpPanelView(service, available=True)
        interaction = object()
        await view.children[0].callback(interaction)
        assert service.calls == [("send_command_guide", interaction)]

    asyncio.run(scenario())


def test_cog_lifecycle_and_events_delegate(tmp_path: Path, monkeypatch) -> None:
    async def scenario() -> None:
        cog, bot = make_cog(tmp_path, monkeypatch)
        message = object()

        await cog.cog_load()
        await cog.on_ready()
        await cog.on_message(message)
        await cog.cog_unload()

        assert len(bot.views) == 1
        assert bot.views[0].timeout is None
        assert cog.service.calls == [
            ("initialize",),
            ("ensure_panel",),
            ("handle_message", message),
            ("shutdown",),
        ]

    asyncio.run(scenario())


def test_setup_adds_cog_and_main_registers_extension(
    tmp_path: Path,
    monkeypatch,
) -> None:
    async def scenario() -> None:
        monkeypatch.setattr(bump_cog, "get_config", lambda: config(tmp_path))
        monkeypatch.setattr(bump_cog, "BumpPanelService", ServiceFake)
        bot = BotFake()
        await bump_cog.setup(bot)
        assert len(bot.cogs) == 1
        assert isinstance(bot.cogs[0], bump_cog.BumpPanelCog)

    asyncio.run(scenario())
    assert "cogs.bump_panel" in main.COGS
