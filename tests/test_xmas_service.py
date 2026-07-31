import asyncio
import json
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

import services.xmas_service as xmas
from services.xmas_service import STATE_NONE, XmasService, t_reward


class FakeResponse:
    def __init__(self) -> None:
        self.sent = []
        self.deferred = []

    async def send_message(self, *args, **kwargs) -> None:
        self.sent.append((args, kwargs))

    async def defer(self, **kwargs) -> None:
        self.deferred.append(kwargs)


class FakeFollowup:
    def __init__(self) -> None:
        self.sent = []

    async def send(self, *args, **kwargs) -> None:
        self.sent.append((args, kwargs))


class FakeMember:
    def __init__(self, user_id: int, *, nick=None, display_name="利用者") -> None:
        self.id = user_id
        self.nick = nick
        self.display_name = display_name
        self.display_avatar = SimpleNamespace(url="https://example.invalid/avatar.png")
        self.edits = []

    async def edit(self, **kwargs) -> None:
        self.edits.append(kwargs)
        self.nick = kwargs["nick"]


class RepositoryStub:
    def __init__(self, original=None, panel_message_id: int = 0) -> None:
        self.original = original
        self.panel_message_id = panel_message_id
        self.calls = []

    def get_original_nickname(self, guild_id: int, user_id: int):
        self.calls.append(("get_original", guild_id, user_id))
        return self.original

    def save_original_nickname(self, guild_id: int, user_id: int, nickname):
        self.calls.append(("save_original", guild_id, user_id, nickname))
        self.original = STATE_NONE if nickname is None else nickname
        return True

    def delete_original_nickname(self, guild_id: int, user_id: int) -> bool:
        self.calls.append(("delete_original", guild_id, user_id))
        self.original = None
        return True

    def get_original_user_ids(self, guild_id: int) -> list[int]:
        self.calls.append(("get_user_ids", guild_id))
        return []

    def get_panel_message_id(self) -> int:
        self.calls.append(("get_panel",))
        return self.panel_message_id

    def set_panel_message_id(self, message_id: int) -> None:
        self.calls.append(("set_panel", message_id))
        self.panel_message_id = message_id

    def save(self) -> None:
        self.calls.append(("save",))


def _service(tmp_path: Path, *, bot=None, channel_id: int = 0) -> XmasService:
    return XmasService(
        bot if bot is not None else object(),
        csv_path=tmp_path / "rewards.csv",
        state_path=tmp_path / "state.json",
        channel_id=channel_id,
        cutoff="2025-12-26T07:00:00+09:00",
        panel_view_factory=lambda: "panel-view",
        result_view_factory=lambda: "result-view",
    )


def test_service_delegates_original_nickname_to_repository(tmp_path: Path) -> None:
    service = _service(tmp_path)
    repository = RepositoryStub()
    service._repository = repository

    service._save_orig_once(10, 20, FakeMember(20, nick="元＠景品"))
    service._restore_target_from_state_or_nick(10, FakeMember(20))

    assert repository.calls == [
        ("save_original", 10, 20, "元"),
        ("get_original", 10, 20),
    ]


def test_repository_exception_propagates_from_service(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service(tmp_path)

    class FailingRepository(RepositoryStub):
        def save(self) -> None:
            raise RuntimeError("save failed")

    service._repository = FailingRepository(original="元")
    member = FakeMember(20, nick="元＠景品")
    interaction = SimpleNamespace(
        guild=SimpleNamespace(id=10),
        user=member,
        response=FakeResponse(),
    )
    monkeypatch.setattr(xmas.discord, "Member", FakeMember)
    with pytest.raises(RuntimeError, match="save failed"):
        asyncio.run(service.revert(interaction))


def test_orig_nick_is_saved_once_and_none_uses_sentinel(tmp_path: Path) -> None:
    service = _service(tmp_path)
    member = FakeMember(20, nick=None)
    service._save_orig_once(10, 20, member)
    service._save_orig_once(10, 20, FakeMember(20, nick="別名"))

    assert service._repository.get_original_nickname(10, 20) == STATE_NONE
    service._repository.save()
    assert json.loads((tmp_path / "state.json").read_text(encoding="utf-8")) == {
        "orig_nick": {"10": {"20": "__NONE__"}},
        "panel_message_id": 0,
    }


def test_pull_saves_original_changes_nickname_and_sends_existing_embed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service(tmp_path)
    member = FakeMember(20, nick="元の名前＠旧", display_name="元の名前＠旧")
    response = FakeResponse()
    interaction = SimpleNamespace(
        guild=SimpleNamespace(id=10), user=member, response=response
    )
    reward = t_reward(1, "UR", "🎁", "特賞", "犬のお守り", "日本語説明")
    monkeypatch.setattr(xmas.discord, "Member", FakeMember)
    monkeypatch.setattr(service, "is_closed", lambda: False)
    monkeypatch.setattr(service, "read_csv_rewards", lambda: [reward])
    monkeypatch.setattr(service, "pick_reward", lambda _rewards: reward)

    asyncio.run(service.pull(interaction))

    assert member.edits == [
        {"nick": "元の名前＠犬のお守り", "reason": "Xmas gacha nickname"}
    ]
    saved = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    assert saved["orig_nick"] == {"10": {"20": "元の名前"}}
    _args, kwargs = response.sent[0]
    assert kwargs["ephemeral"] is True
    assert kwargs["view"] == "result-view"
    assert kwargs["embed"].title == "🎁 特賞 〔UR〕"
    assert kwargs["embed"].description == "日本語説明"
    assert kwargs["embed"].fields[0].value == "`元の名前＠犬のお守り`"


def test_revert_restores_none_and_clears_saved_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service(tmp_path)
    member = FakeMember(20, nick="利用者＠贈り物")
    service._repository.save_original_nickname(10, 20, None)
    response = FakeResponse()
    interaction = SimpleNamespace(
        guild=SimpleNamespace(id=10), user=member, response=response
    )
    monkeypatch.setattr(xmas.discord, "Member", FakeMember)

    asyncio.run(service.revert(interaction))

    assert member.edits == [{"nick": None, "reason": "Xmas gacha nickname"}]
    assert service._repository.get_original_nickname(10, 20) is None
    assert response.sent == [(('🎄まほうはおしまい🎄',), {"ephemeral": True})]


def test_revert_all_restores_recorded_and_salvage_members(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorded = FakeMember(20, nick="元＠景品")
    salvage = FakeMember(21, nick="救済＠景品")
    members = {20: recorded, 21: salvage}
    guild = SimpleNamespace(
        id=10,
        chunked=True,
        members=[recorded, salvage],
        get_member=members.get,
    )
    service = _service(tmp_path)
    service._repository.save_original_nickname(10, 20, "元")
    interaction = SimpleNamespace(
        guild=guild,
        response=FakeResponse(),
        followup=FakeFollowup(),
    )
    monkeypatch.setattr(xmas.discord, "Member", FakeMember)

    async def no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(xmas.asyncio, "sleep", no_sleep)
    asyncio.run(service.revert_all(interaction))

    assert recorded.nick == "元"
    assert salvage.nick == "救済"
    assert service._repository.get_original_nickname(10, 20) is None
    assert interaction.response.deferred == [{"ephemeral": True, "thinking": True}]
    assert "✅ 成功：2" in interaction.followup.sent[0][0][0]


def test_nickname_api_failure_logs_fixed_message_without_nickname(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret_nickname = "private-nickname"

    class FakeDiscordError(Exception):
        pass

    class FailingMember:
        async def edit(self, **kwargs) -> None:
            raise FakeDiscordError

    monkeypatch.setattr(xmas.discord, "Forbidden", FakeDiscordError)
    monkeypatch.setattr(xmas.discord, "HTTPException", FakeDiscordError)
    with caplog.at_level(logging.ERROR, logger=xmas.__name__):
        result = asyncio.run(XmasService._try_set_nick(FailingMember(), secret_nickname))

    assert result is False
    assert "Failed to update an Xmas nickname" in caplog.text
    assert secret_nickname not in caplog.text


def test_panel_message_id_is_saved_after_panel_creation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeChannel:
        async def send(self, **kwargs):
            return SimpleNamespace(id=999)

    channel = FakeChannel()

    class BotStub:
        async def wait_until_ready(self) -> None:
            return None

        def get_channel(self, _channel_id: int):
            return channel

    service = _service(tmp_path, bot=BotStub(), channel_id=123)
    monkeypatch.setattr(xmas.discord, "TextChannel", FakeChannel)

    asyncio.run(service.ensure_panel())

    assert service._repository.get_panel_message_id() == 999
    assert json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))[
        "panel_message_id"
    ] == 999
