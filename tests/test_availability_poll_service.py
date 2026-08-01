import asyncio
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

import services.availability_poll_service as poll_module
from repositories.availability_poll_repository import AvailabilityPollRepository
from services.availability_poll_service import (
    POLL_TEXT,
    AvailabilityPollService,
    footprint_count,
    result_lines,
)

NOW = datetime(2026, 8, 3, 10, 0, tzinfo=timezone.utc)


class Response:
    def __init__(self) -> None:
        self.sent = []

    def is_done(self) -> bool:
        return False

    async def send_message(self, *args, **kwargs) -> None:
        self.sent.append((args, kwargs))


class Message:
    def __init__(self, message_id: int) -> None:
        self.id = message_id
        self.edits = []
        self.embeds = []

    async def edit(self, **kwargs) -> None:
        self.edits.append(kwargs)


class Channel:
    def __init__(self, channel_id: int, guild=None) -> None:
        self.id = channel_id
        self.guild = guild
        self.sent = []
        self.messages = {}
        self.next_id = 100

    async def send(self, **kwargs):
        self.sent.append(kwargs)
        message = Message(self.next_id)
        self.messages[message.id] = message
        self.next_id += 1
        return message

    async def fetch_message(self, message_id: int):
        return self.messages[message_id]


class Guild:
    def __init__(self, guild_id: int) -> None:
        self.id = guild_id
        self.channels = {}

    def get_channel(self, channel_id: int):
        return self.channels.get(channel_id)


class Bot:
    def __init__(self, public: Channel | None, audit_guild: Guild | None) -> None:
        self.public = public
        self.audit_guild = audit_guild

    def get_channel(self, channel_id: int):
        return self.public if self.public and self.public.id == channel_id else None

    def get_guild(self, guild_id: int):
        return self.audit_guild if self.audit_guild and self.audit_guild.id == guild_id else None

    async def fetch_channel(self, channel_id: int):
        return self.audit_guild.channels[channel_id]


def make_service(
    tmp_path: Path,
    *,
    public: Channel | None = None,
    audit: Channel | None = None,
    sleep=asyncio.sleep,
    now=NOW,
):
    guild = Guild(30)
    if audit is not None:
        audit.guild = guild
        guild.channels[audit.id] = audit
    repository = AvailabilityPollRepository(tmp_path / "runtime" / "poll.json")
    service = AvailabilityPollService(
        bot=Bot(public, guild),
        repository=repository,
        channel_id=10,
        timezone_name="Asia/Tokyo",
        weekday_windows=("20:00-21:00",),
        holiday_windows=("13:00-14:00", "20:00-21:00"),
        audit_guild_id=30,
        audit_channel_id=40,
        view_factory=lambda poll_id, disabled: (poll_id, disabled),
        now_factory=lambda: now,
        sleep_func=sleep,
        randrange=lambda start, _end: start,
        holiday_checker=lambda _day: False,
    )
    return service, repository


def interaction(message: Message, *, user_id=7, bot=False):
    user = SimpleNamespace(
        id=user_id,
        bot=bot,
        mention=f"<@{user_id}>",
        display_name="private-name",
    )
    return SimpleNamespace(
        user=user,
        message=message,
        response=Response(),
        followup=SimpleNamespace(send=None),
        guild=SimpleNamespace(id=50),
        guild_id=50,
    )


def prepare_poll(repository, message_id=100, poll_id="poll") -> None:
    repository.load()
    repository.create_poll(
        poll_id=poll_id,
        message_id=message_id,
        channel_id=10,
        opened_at=NOW,
    )


def test_public_text_counts_and_footprints_are_anonymous(tmp_path: Path) -> None:
    service, repository = make_service(tmp_path)
    repository.load()
    embed = service.public_embed(
        "poll",
        {"valorant": 0, "other_game": 3, "work_vc": 12},
    )
    assert POLL_TEXT in embed.description
    assert "🎯 VALORANT　（0）" in embed.description
    assert "🎮 その他ゲーム　🐾🐾🐾（3）" in embed.description
    assert "🗣️ 作業VC　🐾×12（12）" in embed.description
    assert footprint_count(10) == "🐾" * 10
    assert footprint_count(11) == "🐾×11"
    assert "private" not in embed.description
    assert result_lines({"valorant": 1, "other_game": 2, "work_vc": 3}, icons=False) == (
        "VALORANT 1人\nその他ゲーム 2人\n作業VC 3人"
    )


def test_initialize_reuses_future_next_run_and_single_task(tmp_path: Path) -> None:
    calls = []

    async def sleep(seconds):
        calls.append(seconds)
        await asyncio.Event().wait()

    async def scenario():
        service, repository = make_service(tmp_path, sleep=sleep)
        repository.load()
        future = NOW + timedelta(hours=2)
        repository.set_next_run_at(future)
        repository.save()
        await service.initialize()
        first = service._scheduler_task
        await asyncio.sleep(0)
        assert calls == [7200]
        assert repository.get_next_run_at() == future
        await service.initialize()
        assert service._scheduler_task is not first
        await service.shutdown()

    asyncio.run(scenario())


def test_past_next_run_is_not_posted_and_is_recalculated(tmp_path: Path) -> None:
    async def sleep(_seconds):
        await asyncio.Event().wait()

    async def scenario():
        public = Channel(10)
        service, repository = make_service(tmp_path, public=public, sleep=sleep)
        repository.load()
        repository.set_next_run_at(NOW - timedelta(hours=1))
        repository.save()
        await service.initialize()
        assert not public.sent
        assert repository.get_next_run_at() > NOW
        await service.shutdown()

    asyncio.run(scenario())


@pytest.mark.parametrize("answer", ["valorant", "other_game", "work_vc"])
def test_answer_add_change_same_and_cancel_with_audit(tmp_path: Path, answer: str) -> None:
    async def scenario():
        public = Channel(10)
        audit = Channel(40)
        service, repository = make_service(tmp_path, public=public, audit=audit)
        message = Message(100)
        prepare_poll(repository)
        first = interaction(message)
        await service.handle_answer(first, answer, "poll")
        assert repository.get_answer(7) == answer
        assert first.response.sent[0][1]["ephemeral"] is True
        assert message.edits
        assert len(audit.sent) == 1
        assert "private-name" not in message.edits[0]["embed"].description
        assert "private-name" in audit.sent[0]["embed"].description

        same = interaction(message)
        await service.handle_answer(same, answer, "poll")
        assert "もうあしあと" in same.response.sent[0][0][0]
        assert len(audit.sent) == 2

        changed = interaction(message)
        replacement = "work_vc" if answer != "work_vc" else "valorant"
        await service.handle_answer(changed, replacement, "poll")
        assert repository.get_answer(7) == replacement
        assert "回答変更" in audit.sent[2]["embed"].description

        cancelled = interaction(message)
        await service.handle_answer(cancelled, None, "poll")
        assert repository.get_answer(7) is None
        assert "回答取消" in audit.sent[3]["embed"].description

    asyncio.run(scenario())


def test_invalid_poll_message_and_bot_do_not_save_or_audit(tmp_path: Path) -> None:
    async def scenario():
        audit = Channel(40)
        service, repository = make_service(tmp_path, audit=audit)
        prepare_poll(repository)
        await service.handle_answer(interaction(Message(999)), "valorant", "poll")
        await service.handle_answer(interaction(Message(100), bot=True), "valorant", "poll")
        await service.handle_answer(interaction(Message(100)), "valorant", "old")
        assert repository.get_counts() == {"valorant": 0, "other_game": 0, "work_vc": 0}
        assert not audit.sent

    asyncio.run(scenario())


def test_save_failure_rolls_back_and_sends_no_audit(tmp_path: Path, monkeypatch) -> None:
    async def scenario():
        audit = Channel(40)
        service, repository = make_service(tmp_path, audit=audit)
        prepare_poll(repository)

        def fail():
            raise OSError("secret")

        monkeypatch.setattr(repository, "save", fail)
        await service.handle_answer(interaction(Message(100)), "valorant", "poll")
        assert repository.get_answer(7) is None
        assert not audit.sent

    asyncio.run(scenario())


def test_skip_stop_resume_persist_and_are_idempotent(tmp_path: Path) -> None:
    async def sleep(_seconds):
        await asyncio.Event().wait()

    async def scenario():
        audit = Channel(40)
        service, repository = make_service(tmp_path, audit=audit, sleep=sleep)
        repository.load()
        repository.set_next_run_at(NOW + timedelta(hours=1))
        repository.save()
        service._replace_scheduler(repository.get_next_run_at())

        await service.skip_next(interaction(Message(1)))
        assert repository.should_skip_next_run() is True
        await service.skip_next(interaction(Message(1)))
        assert len(audit.sent) == 1

        active_task = service._scheduler_task
        await service.stop(interaction(Message(1)))
        assert repository.is_paused() is True
        assert repository.should_skip_next_run() is False
        assert repository.get_next_run_at() is None
        assert active_task.cancelled()
        await service.stop(interaction(Message(1)))
        assert len(audit.sent) == 2

        await service.resume(interaction(Message(1)))
        assert repository.is_paused() is False
        assert repository.get_next_run_at() > NOW
        assert service._scheduler_task is not None
        await service.resume(interaction(Message(1)))
        assert len(audit.sent) == 3
        await service.shutdown()

    asyncio.run(scenario())


def test_skip_is_consumed_once_and_next_run_posts(tmp_path: Path) -> None:
    async def sleep(_seconds):
        await asyncio.Event().wait()

    async def scenario():
        public = Channel(10)
        service, repository = make_service(tmp_path, public=public, sleep=sleep)
        repository.load()
        repository.set_skip_next_run(True)
        repository.set_next_run_at(NOW)
        repository.save()

        await service._run_scheduled(NOW)
        assert repository.should_skip_next_run() is False
        assert not public.sent
        next_run = repository.get_next_run_at()
        assert next_run is not None

        await service._run_scheduled(next_run)
        assert len(public.sent) == 1
        assert repository.get_active_poll() is not None
        await service.shutdown()

    asyncio.run(scenario())


def test_audit_failure_does_not_rollback_answer(tmp_path: Path, monkeypatch, caplog) -> None:
    class SendError(Exception):
        pass

    monkeypatch.setattr(poll_module.discord, "Forbidden", SendError)

    async def scenario():
        audit = Channel(40)

        async def fail_send(**_kwargs):
            raise SendError()

        audit.send = fail_send
        service, repository = make_service(tmp_path, audit=audit)
        prepare_poll(repository)
        with caplog.at_level(logging.ERROR):
            await service.handle_answer(interaction(Message(100)), "valorant", "poll")
        assert repository.get_answer(7) == "valorant"
        assert "Failed to send" in caplog.text
        assert "private-name" not in caplog.text
        assert "valorant" not in caplog.text

    asyncio.run(scenario())
