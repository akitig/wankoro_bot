import asyncio
import importlib

omikuji_cog = importlib.import_module("cogs.2026_omikuji_gacha")


class ServiceStub:
    def __init__(self) -> None:
        self.calls = []

    async def handle_draw(self, interaction) -> None:
        self.calls.append(("draw", interaction))

    async def handle_points(self, interaction) -> None:
        self.calls.append(("points", interaction))

    async def post_panel(self, interaction, view) -> None:
        self.calls.append(("panel", interaction, view))

    async def reset_points(self, interaction) -> None:
        self.calls.append(("reset", interaction))


def _cog() -> tuple[object, ServiceStub]:
    cog = omikuji_cog.OmikujiGachaCog.__new__(omikuji_cog.OmikujiGachaCog)
    service = ServiceStub()
    cog.service = service
    cog._view = object()
    return cog, service


def test_cog_delegates_business_operations_to_service() -> None:
    cog, service = _cog()
    interaction = object()

    asyncio.run(cog.handle_draw(interaction))
    asyncio.run(cog.handle_points(interaction))
    asyncio.run(omikuji_cog.OmikujiGachaCog.omikuji_panel.callback(cog, interaction))
    asyncio.run(
        omikuji_cog.OmikujiGachaCog.omikuji_reset_points.callback(cog, interaction)
    )

    assert service.calls == [
        ("draw", interaction),
        ("points", interaction),
        ("panel", interaction, cog._view),
        ("reset", interaction),
    ]


def test_command_metadata_is_preserved() -> None:
    panel = omikuji_cog.OmikujiGachaCog.omikuji_panel
    reset = omikuji_cog.OmikujiGachaCog.omikuji_reset_points

    assert panel.name == "omikuji_panel"
    assert panel.description == "初春おみくじガチャのパネルを指定チャンネルに投稿します"
    assert reset.name == "omikuji_reset_points"
    assert reset.description == (
        "全員のポイントを初期値（500pt）にリセットします（指定ユーザーのみ）"
    )


def test_view_timeout_metadata_and_button_callbacks_are_preserved() -> None:
    cog, service = _cog()
    interaction = object()

    async def scenario():
        view = omikuji_cog.OmikujiView(cog)
        await view.draw_button.callback(interaction)
        await view.points_button.callback(interaction)
        return view

    view = asyncio.run(scenario())

    assert view.timeout is None
    assert view.draw_button.label == "🎴 おみくじを引く（50pt）"
    assert view.draw_button.custom_id == "omikuji:draw_2026"
    assert view.points_button.label == "💰 ポイント確認"
    assert view.points_button.custom_id == "omikuji:points_2026"
    assert service.calls == [("draw", interaction), ("points", interaction)]
