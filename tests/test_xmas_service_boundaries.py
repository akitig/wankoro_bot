import asyncio
import importlib

xmas_cog = importlib.import_module("cogs.2025_xmas_gacha")


class ServiceStub:
    def __init__(self) -> None:
        self.calls = []

    async def revert(self, interaction) -> None:
        self.calls.append(("revert", interaction))

    async def pull(self, interaction) -> None:
        self.calls.append(("pull", interaction))

    async def ensure_panel(self) -> None:
        self.calls.append(("ensure_panel",))

    async def send_panel(self, interaction) -> None:
        self.calls.append(("panel", interaction))

    async def revert_all(self, interaction) -> None:
        self.calls.append(("revert_all", interaction))


def _cog() -> tuple[object, ServiceStub]:
    cog = xmas_cog.t_xmas_gacha.__new__(xmas_cog.t_xmas_gacha)
    service = ServiceStub()
    cog.service = service
    return cog, service


def test_cog_commands_and_event_delegate_to_service() -> None:
    cog, service = _cog()
    interaction = object()

    asyncio.run(cog.on_ready())
    asyncio.run(xmas_cog.t_xmas_gacha.xmas_gacha_panel.callback(cog, interaction))
    asyncio.run(
        xmas_cog.t_xmas_gacha.xmas_gacha_revert_all.callback(cog, interaction)
    )

    assert service.calls == [
        ("ensure_panel",),
        ("panel", interaction),
        ("revert_all", interaction),
    ]


def test_command_metadata_is_preserved() -> None:
    panel = xmas_cog.t_xmas_gacha.xmas_gacha_panel
    revert = xmas_cog.t_xmas_gacha.xmas_gacha_revert_all
    assert panel.name == "xmas_gacha_panel"
    assert panel.description == "クリスマスガチャのパネルを送信（手動）"
    assert revert.name == "xmas_gacha_revert_all"
    assert revert.description == "ガチャで変わった名前を、可能な限り全員戻す"


def test_view_metadata_and_callbacks_are_preserved() -> None:
    cog, service = _cog()
    interaction = object()

    async def scenario():
        panel_view = xmas_cog.t_xmas_gacha_view(cog)
        result_view = xmas_cog.t_xmas_gacha_result_view(cog)
        await panel_view.pull.callback(interaction)
        await result_view.revert.callback(interaction)
        return panel_view, result_view

    panel_view, result_view = asyncio.run(scenario())
    assert panel_view.timeout is None
    assert panel_view.pull.label == "🎁 ガチャを引く"
    assert panel_view.pull.style == xmas_cog.discord.ButtonStyle.success
    assert panel_view.pull.custom_id == "xmas_gacha:pull"
    assert result_view.timeout == 300
    assert result_view.revert.label == "↩️ 名前を戻す"
    assert result_view.revert.style == xmas_cog.discord.ButtonStyle.secondary
    assert result_view.revert.custom_id == "xmas_gacha:revert"
    assert service.calls == [("pull", interaction), ("revert", interaction)]


def test_cog_load_registers_persistent_view() -> None:
    cog, _service = _cog()

    class BotStub:
        def __init__(self) -> None:
            self.views = []

        def add_view(self, view) -> None:
            self.views.append(view)

    bot = BotStub()
    cog.bot = bot
    asyncio.run(cog.cog_load())
    assert len(bot.views) == 1
    assert isinstance(bot.views[0], xmas_cog.t_xmas_gacha_view)
    assert bot.views[0].timeout is None
