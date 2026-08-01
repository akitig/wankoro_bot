import asyncio
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

import services.bump_panel_service as bump_service
from repositories.bump_panel_repository import BumpPanelRepository
from services.bump_panel_service import BumpPanelService, is_bump_success_message

NOW = datetime(2026, 8, 1, 3, 0, tzinfo=timezone.utc)


class FakePanelMessage:
    def __init__(self, message_id: int) -> None:
        self.id = message_id
        self.edits: list[dict[str, object]] = []
        self.deleted = False
        self.delete_error: Exception | None = None

    async def edit(self, **kwargs: object) -> None:
        self.edits.append(kwargs)

    async def delete(self) -> None:
        if self.delete_error:
            raise self.delete_error
        self.deleted = True


class FakeChannel:
    def __init__(self, channel_id: int = 10) -> None:
        self.id = channel_id
        self.messages: dict[int, FakePanelMessage] = {}
        self.sent: list[dict[str, object]] = []
        self.next_id = 100
        self.fetch_error: Exception | None = None

    async def fetch_message(self, message_id: int) -> FakePanelMessage:
        if self.fetch_error:
            raise self.fetch_error
        return self.messages[message_id]

    async def send(self, **kwargs: object) -> FakePanelMessage:
        self.sent.append(kwargs)
        message = FakePanelMessage(self.next_id)
        self.messages[message.id] = message
        self.next_id += 1
        return message


class FakeBot:
    def __init__(self, channel: FakeChannel | None) -> None:
        self.channel = channel

    def get_channel(self, channel_id: int) -> FakeChannel | None:
        if self.channel is not None and self.channel.id == channel_id:
            return self.channel
        return None


def make_service(
    tmp_path: Path,
    *,
    channel: FakeChannel | None = None,
    command_id: int | None = 30,
    now: datetime = NOW,
    sleep_func=asyncio.sleep,
) -> tuple[BumpPanelService, BumpPanelRepository]:
    repository = BumpPanelRepository(tmp_path / "runtime" / "bump.json")
    service = BumpPanelService(
        bot=FakeBot(channel),
        repository=repository,
        channel_id=10,
        disboard_bot_id=20,
        bump_command_id=command_id,
        cooldown_seconds=7200,
        view_factory=lambda available: f"view:{available}",
        now_factory=lambda: now,
        sleep_func=sleep_func,
    )
    return service, repository


def message(
    *,
    channel_id: int = 10,
    author_id: int = 20,
    command_name: str | None = "bump",
    content: str = "",
    embeds: list[object] | None = None,
) -> SimpleNamespace:
    metadata = (
        SimpleNamespace(name=command_name) if command_name is not None else None
    )
    return SimpleNamespace(
        channel=SimpleNamespace(id=channel_id),
        author=SimpleNamespace(id=author_id),
        interaction_metadata=metadata,
        content=content,
        embeds=embeds or [],
    )


@pytest.mark.parametrize(
    ("candidate", "expected"),
    [
        (message(), True),
        (message(channel_id=11), False),
        (message(author_id=21), False),
        (message(command_name="help"), False),
        (message(author_id=99, content="/bump"), False),
        (message(command_name=None, content="unrelated response"), False),
        (message(command_name=None, content="Bump done! Thanks"), True),
        (
            message(
                command_name=None,
                embeds=[SimpleNamespace(
                    title="BUMP成功",
                    description="表示順を更新しました",
                    author=None,
                    footer=None,
                )],
            ),
            True,
        ),
    ],
)
def test_bump_success_detection(candidate: object, expected: bool) -> None:
    assert is_bump_success_message(
        candidate,
        channel_id=10,
        disboard_bot_id=20,
    ) is expected


def test_initial_and_past_state_are_available(tmp_path: Path) -> None:
    service, repository = make_service(tmp_path)
    repository.load()
    assert service.is_available() is True
    repository.set_bump_times(
        last_bumped_at=NOW - timedelta(hours=3),
        next_bump_at=NOW - timedelta(hours=1),
    )
    assert service.is_available() is True


def test_future_state_is_waiting(tmp_path: Path) -> None:
    service, repository = make_service(tmp_path)
    repository.load()
    repository.set_bump_times(
        last_bumped_at=NOW,
        next_bump_at=NOW + timedelta(hours=2),
    )
    assert service.is_available() is False


def test_initialize_updates_existing_panel_and_sleeps_remaining_time(
    tmp_path: Path,
) -> None:
    sleeps: list[float] = []
    blocker = asyncio.Event()

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        await blocker.wait()

    async def scenario() -> None:
        channel = FakeChannel()
        panel = FakePanelMessage(44)
        channel.messages[44] = panel
        service, repository = make_service(
            tmp_path,
            channel=channel,
            sleep_func=sleep,
        )
        repository.load()
        repository.set_bump_times(
            last_bumped_at=NOW,
            next_bump_at=NOW + timedelta(minutes=30),
        )
        repository.set_panel_message_id(44)
        repository.save()

        await service.initialize()
        await asyncio.sleep(0)

        assert sleeps == [1800]
        assert panel.edits[0]["view"] == "view:False"
        await service.shutdown()

    asyncio.run(scenario())


def test_bump_success_saves_times_reposts_panel_and_finishes_cooldown(
    tmp_path: Path,
) -> None:
    sleeps: list[float] = []

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)

    async def scenario() -> None:
        channel = FakeChannel()
        old_panel = FakePanelMessage(44)
        channel.messages[44] = old_panel
        service, repository = make_service(
            tmp_path,
            channel=channel,
            sleep_func=sleep,
        )
        repository.load()
        repository.set_panel_message_id(44)

        await service.record_bump_success()
        assert repository.get_last_bumped_at() == NOW
        assert repository.get_next_bump_at() == NOW + timedelta(seconds=7200)
        assert old_panel.deleted is True
        assert channel.sent[0]["view"] == "view:False"
        assert repository.get_panel_message_id() == 100

        await asyncio.sleep(0)
        assert sleeps == [7200]
        assert repository.get_next_bump_at() is None
        assert channel.messages[100].edits[-1]["view"] == "view:True"
        await service.shutdown()

    asyncio.run(scenario())


def test_new_bump_cancels_existing_task(tmp_path: Path) -> None:
    cancelled = asyncio.Event()

    async def sleep(_seconds: float) -> None:
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    async def scenario() -> None:
        service, repository = make_service(
            tmp_path,
            channel=FakeChannel(),
            sleep_func=sleep,
        )
        repository.load()
        await service.record_bump_success()
        first_task = service._cooldown_task
        await asyncio.sleep(0)
        await service.record_bump_success()
        await asyncio.sleep(0)
        assert first_task is not None and first_task.cancelled()
        assert cancelled.is_set()
        assert service._cooldown_task is not first_task
        await service.shutdown()

    asyncio.run(scenario())


def test_delete_failure_still_posts_new_panel(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    class DeleteError(Exception):
        pass

    monkeypatch.setattr(bump_service.discord, "Forbidden", DeleteError)

    async def scenario() -> None:
        channel = FakeChannel()
        old_panel = FakePanelMessage(44)
        old_panel.delete_error = DeleteError()
        channel.messages[44] = old_panel
        service, repository = make_service(tmp_path, channel=channel)
        repository.load()
        repository.set_panel_message_id(44)
        with caplog.at_level(logging.ERROR):
            await service.record_bump_success()
        assert len(channel.sent) == 1
        assert "Failed to delete" in caplog.text
        await service.shutdown()

    asyncio.run(scenario())


def test_missing_panel_is_recreated(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class NotFoundError(Exception):
        pass

    monkeypatch.setattr(bump_service.discord, "NotFound", NotFoundError)

    async def scenario() -> None:
        channel = FakeChannel()
        channel.fetch_error = NotFoundError()
        service, repository = make_service(tmp_path, channel=channel)
        repository.load()
        repository.set_panel_message_id(44)
        await service.ensure_panel()
        assert len(channel.sent) == 1
        assert repository.get_panel_message_id() == 100

    asyncio.run(scenario())


def test_channel_unavailable_is_safe(tmp_path: Path, caplog) -> None:
    async def scenario() -> None:
        service, repository = make_service(tmp_path)
        repository.load()
        with caplog.at_level(logging.WARNING):
            await service.ensure_panel()
        assert "unavailable" in caplog.text

    asyncio.run(scenario())


def test_uncertain_disboard_message_does_not_log_content(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def scenario() -> None:
        service, repository = make_service(tmp_path)
        repository.load()
        private_content = "private-message-body"
        with caplog.at_level(logging.WARNING):
            await service.handle_message(
                message(command_name=None, content=private_content)
            )
        assert "Unable to confirm" in caplog.text
        assert private_content not in caplog.text
        assert repository.get_next_bump_at() is None

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("command_id", "expected"),
    [
        (30, "BUMPはこちら：</bump:30>"),
        (None, "このチャンネルで /bump を入力し、\nDISBOARDのコマンドを選択してください。"),
    ],
)
def test_command_guide_is_ephemeral_and_does_not_change_state(
    tmp_path: Path,
    command_id: int | None,
    expected: str,
) -> None:
    class Response:
        def __init__(self) -> None:
            self.calls: list[tuple[str, bool]] = []

        def is_done(self) -> bool:
            return False

        async def send_message(self, text: str, *, ephemeral: bool) -> None:
            self.calls.append((text, ephemeral))

    async def scenario() -> None:
        service, repository = make_service(tmp_path, command_id=command_id)
        repository.load()
        response = Response()
        interaction = SimpleNamespace(response=response, followup=None)
        await service.send_command_guide(interaction)
        assert response.calls == [(expected, True)]
        assert repository.get_last_bumped_at() is None
        assert repository.get_next_bump_at() is None
        assert not (tmp_path / "runtime" / "bump.json").exists()

    asyncio.run(scenario())


def test_shutdown_cancels_wait_task(tmp_path: Path) -> None:
    async def sleep(_seconds: float) -> None:
        await asyncio.Event().wait()

    async def scenario() -> None:
        service, repository = make_service(tmp_path, sleep_func=sleep)
        repository.load()
        service._schedule_cooldown(NOW + timedelta(hours=2))
        task = service._cooldown_task
        await asyncio.sleep(0)
        await service.shutdown()
        assert task is not None and task.cancelled()

    asyncio.run(scenario())


def test_cooldown_task_logs_unexpected_failure(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def no_sleep(_seconds: float) -> None:
        return None

    async def scenario() -> None:
        service, repository = make_service(tmp_path, sleep_func=no_sleep)
        repository.load()

        def fail_save() -> None:
            raise OSError("private failure detail")

        repository.save = fail_save  # type: ignore[method-assign]
        with caplog.at_level(logging.ERROR):
            service._schedule_cooldown(NOW + timedelta(hours=2))
            task = service._cooldown_task
            assert task is not None
            await task
        assert "Unexpected failure in the BUMP cooldown task" in caplog.text

    asyncio.run(scenario())
