import asyncio
import importlib

valomap_cog = importlib.import_module("cogs.valomap")


class ResponseStub:
    def __init__(self) -> None:
        self.sent = []
        self.edited = []

    async def send_message(self, *args, **kwargs) -> None:
        self.sent.append((args, kwargs))

    async def edit_message(self, *args, **kwargs) -> None:
        self.edited.append((args, kwargs))


class ServiceStub:
    def __init__(self) -> None:
        self.calls = []
        self.listing = [("Ascent", False), ("Bind", True)]
        self.available = [{"displayName": "Ascent", "splash": "https://image"}]
        self.selected = self.available[0]

    async def get_map_listing(self):
        self.calls.append(("listing",))
        return self.listing

    async def get_available_maps(self):
        self.calls.append(("available",))
        return self.available

    async def select_random_map(self):
        self.calls.append(("select",))
        return self.selected

    def is_banned(self, _name):
        return False

    def ban_map(self, name):
        self.calls.append(("ban", name))

    def clear_bans(self):
        self.calls.append(("clear",))

    async def initialize(self):
        self.calls.append(("initialize",))


def _cog() -> tuple[object, ServiceStub]:
    cog = valomap_cog.ValorantMap.__new__(valomap_cog.ValorantMap)
    service = ServiceStub()
    cog.service = service
    return cog, service


def test_commands_delegate_and_preserve_embeds_and_ephemeral_behavior() -> None:
    cog, service = _cog()
    response = ResponseStub()
    interaction = type("Interaction", (), {"response": response})()

    asyncio.run(valomap_cog.ValorantMap.valomap_all.callback(cog, interaction))
    asyncio.run(valomap_cog.ValorantMap.valomap_pool.callback(cog, interaction))
    asyncio.run(valomap_cog.ValorantMap.valomap_select.callback(cog, interaction))
    asyncio.run(valomap_cog.ValorantMap.valomap_ban_ui.callback(cog, interaction))
    asyncio.run(valomap_cog.ValorantMap.valomap_clear.callback(cog, interaction))
    asyncio.run(valomap_cog.ValorantMap.valomap_help.callback(cog, interaction))

    assert service.calls == [
        ("listing",),
        ("available",),
        ("select",),
        ("available",),
        ("clear",),
    ]
    assert response.sent[0][1]["embed"].description == "✅ Ascent\n❌ ~~Bind~~"
    assert response.sent[1][1]["embed"].description == "✅ Ascent"
    assert response.sent[2][1]["embed"].description == "**Ascent** が選ばれました！"
    assert response.sent[2][1]["embed"].image.url == "https://image"
    assert response.sent[3][0] == ("BANするマップを選んでください：",)
    assert response.sent[3][1]["ephemeral"] is True
    assert response.sent[4] == (("✅ すべてのマップBANを解除しました。",), {})
    assert response.sent[5][1]["ephemeral"] is True
    assert len(response.sent[5][1]["embed"].fields) == 6


def test_empty_candidate_messages_and_ephemeral_settings_are_preserved() -> None:
    cog, service = _cog()
    service.available = []
    service.selected = None
    response = ResponseStub()
    interaction = type("Interaction", (), {"response": response})()

    asyncio.run(valomap_cog.ValorantMap.valomap_pool.callback(cog, interaction))
    asyncio.run(valomap_cog.ValorantMap.valomap_select.callback(cog, interaction))
    asyncio.run(valomap_cog.ValorantMap.valomap_ban_ui.callback(cog, interaction))

    assert response.sent == [
        (("❌ 現在、利用可能なマップはありません。",), {"ephemeral": True}),
        (("❌ 利用可能なマップがありません。BANを解除してください。",), {}),
        (("❌ すべてのマップがBAN済みです。",), {"ephemeral": True}),
    ]


def test_command_metadata_is_preserved() -> None:
    commands = {
        "valomap_all": ("valomap", "VALORANTの全コンペマップを表示します（BAN済みは❌）"),
        "valomap_pool": ("valomappool", "BANされていないVALORANTマップを表示します"),
        "valomap_select": ("valomapselect", "BANされていないマップからランダムに選びます"),
        "valomap_ban_ui": ("valomapban", "ドロップダウンでBANするマップを選びます"),
        "valomap_clear": ("valomapclear", "すべてのBANを解除します"),
        "valomap_help": ("valocustom", "VALORANTマップ関連コマンド一覧を表示します"),
    }
    for attribute, (name, description) in commands.items():
        command = getattr(valomap_cog.ValorantMap, attribute)
        assert command.name == name
        assert command.description == description


def test_select_options_timeout_and_callback_are_preserved() -> None:
    service = ServiceStub()
    maps = [{"displayName": "Ascent"}, {"displayName": "Bind"}]

    async def scenario():
        view = valomap_cog.ValorantMap.MapBanView(service, maps)
        dropdown = view.children[0]
        dropdown._values = ["Ascent"]
        response = ResponseStub()
        interaction = type("Interaction", (), {"response": response})()
        await dropdown.callback(interaction)
        return view, dropdown, response

    view, dropdown, response = asyncio.run(scenario())
    assert view.timeout == 60
    assert dropdown.placeholder == "BANするマップを選んでください"
    assert [option.label for option in dropdown.options] == ["Ascent", "Bind"]
    assert all(option.description == "BANするマップを選択" for option in dropdown.options)
    assert dropdown.min_values == 1
    assert dropdown.max_values == 1
    assert service.calls == [("ban", "Ascent")]
    assert response.edited == [
        ((), {"content": "🚫 `Ascent` をBANしました。", "view": None})
    ]


def test_on_ready_delegates_only_to_initialize() -> None:
    cog, service = _cog()
    asyncio.run(cog.on_ready())
    assert service.calls == [("initialize",)]
