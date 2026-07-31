import asyncio
from types import SimpleNamespace

import pytest

import services.joya_service as service_module
from services.joya_service import JoyaService


class FakeResponse:
    def __init__(self) -> None:
        self.deferred = False

    def is_done(self) -> bool:
        return self.deferred

    async def defer(self) -> None:
        self.deferred = True


class FakeFollowup:
    def __init__(self) -> None:
        self.sent = []

    async def send(self, *args, **kwargs) -> None:
        self.sent.append((args, kwargs))


class FakeMember:
    def __init__(self, user_id: int) -> None:
        self.id = user_id
        self.mention = f"<@{user_id}>"
        self.roles = []
        self.added_roles = []

    async def add_roles(self, role, **kwargs) -> None:
        self.added_roles.append((role, kwargs))


class FakeGuild:
    def __init__(self, member: FakeMember, role=None) -> None:
        self.id = 10
        self.member = member
        self.role = role

    def get_member(self, user_id: int):
        return self.member if self.member.id == user_id else None

    def get_role(self, role_id: int):
        return self.role

    def get_channel(self, channel_id: int):
        return None


def _service(tmp_path, guild: FakeGuild) -> JoyaService:
    return JoyaService(
        SimpleNamespace(),
        data_path=str(tmp_path / "joya.json"),
        min_sec=60,
        max_sec=300,
        winner_role_id=900,
        channel_id=800,
        view_factory=lambda disabled: object(),
    )


def _interaction(guild: FakeGuild, member: FakeMember):
    return SimpleNamespace(
        guild=guild,
        user=member,
        response=FakeResponse(),
        followup=FakeFollowup(),
    )


def test_normal_ring_updates_state_and_preserves_message(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(service_module.discord, "Member", FakeMember)
    monkeypatch.setattr(service_module, "_now_ts", lambda: 1_000)
    monkeypatch.setattr(service_module, "_choose_cooldown", lambda _min, _max: 30)
    member = FakeMember(20)
    guild = FakeGuild(member)
    service = _service(tmp_path, guild)
    interaction = _interaction(guild, member)

    asyncio.run(service.handle_joya(interaction))

    assert service._get_count_state(guild.id) == (1, False)
    assert service._store.get_user(guild.id, member.id)["next_ts"] == 1_030
    assert interaction.followup.sent == [
        (("**1回目！** ゴーン！ 🔔（次は 30秒）\n（まだ鳴る。まだ戻れる。）",), {})
    ]


def test_final_ring_assigns_role_and_persists_winner(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(service_module.discord, "Member", FakeMember)
    monkeypatch.setattr(service_module, "_now_ts", lambda: 1_000)
    monkeypatch.setattr(service_module, "_choose_cooldown", lambda _min, _max: 30)
    member = FakeMember(20)
    role = object()
    guild = FakeGuild(member, role)
    service = _service(tmp_path, guild)
    service._set_count_state(guild.id, 107, False)
    interaction = _interaction(guild, member)

    asyncio.run(service.handle_joya(interaction))

    state = service._store.get_guild(guild.id)
    assert state["count"] == 108
    assert state["finished"] is True
    assert state["winner_user_id"] == member.id
    assert state["finished_at"] == 1_000
    assert member.added_roles == [(role, {"reason": "Joya 108th winner"})]
    assert interaction.followup.sent[0][1]["embed"].title == (
        "🔔 108回目 —— 除夜の鐘、成就"
    )
