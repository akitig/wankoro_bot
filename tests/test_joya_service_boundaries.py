import asyncio
import importlib

joya_cog = importlib.import_module("cogs.2026_joya_gacha")


class ServiceStub:
    def __init__(self) -> None:
        self.calls = []

    async def handle_joya(self, interaction) -> None:
        self.calls.append(("ring", interaction))

    async def post_panel(self, interaction) -> None:
        self.calls.append(("panel", interaction))

    async def send_status(self, interaction) -> None:
        self.calls.append(("status", interaction))

    async def configure(self, interaction, minimum, maximum) -> None:
        self.calls.append(("configure", interaction, minimum, maximum))

    async def reset_config(self, interaction) -> None:
        self.calls.append(("reset_config", interaction))

    async def reset_all(self, interaction) -> None:
        self.calls.append(("reset_all", interaction))


def _cog() -> tuple[object, ServiceStub]:
    cog = joya_cog.JoyaGacha.__new__(joya_cog.JoyaGacha)
    service = ServiceStub()
    cog.service = service
    return cog, service


def test_slash_commands_delegate_to_service() -> None:
    cog, service = _cog()
    interaction = object()

    asyncio.run(joya_cog.JoyaGacha.joya.callback(cog, interaction))
    asyncio.run(joya_cog.JoyaGacha.joya_panel.callback(cog, interaction))
    asyncio.run(joya_cog.JoyaGacha.joya_status.callback(cog, interaction))
    asyncio.run(
        joya_cog.JoyaGacha.joya_config.callback(cog, interaction, 2, 5)
    )
    asyncio.run(joya_cog.JoyaGacha.joya_config_reset.callback(cog, interaction))
    asyncio.run(joya_cog.JoyaGacha.joya_reset_all.callback(cog, interaction))

    assert service.calls == [
        ("ring", interaction),
        ("panel", interaction),
        ("status", interaction),
        ("configure", interaction, 2, 5),
        ("reset_config", interaction),
        ("reset_all", interaction),
    ]


def test_command_metadata_is_preserved() -> None:
    assert joya_cog.JoyaGacha.joya.name == "joya"
    assert joya_cog.JoyaGacha.joya.description == "除夜の鐘を1回鳴らす"
    assert joya_cog.JoyaGacha.joya_panel.name == "joya_panel"
    assert joya_cog.JoyaGacha.joya_status.name == "joya_status"
    assert joya_cog.JoyaGacha.joya_config.name == "joya_config"
    assert joya_cog.JoyaGacha.joya_config_reset.name == "joya_config_reset"
    assert joya_cog.JoyaGacha.joya_reset_all.name == "joya_reset_all"


def test_view_metadata_is_preserved() -> None:
    async def scenario():
        view = joya_cog.JoyaView()
        return view, view.children[0]

    view, button = asyncio.run(scenario())

    assert button.label == "🔔 除夜の鐘を鳴らす"
    assert button.custom_id == "joya:ring"
    assert view.timeout is None
