import asyncio
from datetime import timedelta

from tests.test_availability_poll_service import (
    NOW,
    Channel,
    Message,
    interaction,
    make_service,
    prepare_poll,
)


def test_manual_post_preserves_schedule_controls_and_audits(tmp_path) -> None:
    async def scenario() -> None:
        public = Channel(10)
        audit = Channel(40)
        service, repository = make_service(tmp_path, public=public, audit=audit)
        repository.load()
        next_run = NOW + timedelta(hours=2)
        repository.set_next_run_at(next_run)
        repository.set_paused(True)
        repository.set_skip_next_run(True)
        repository.save()
        scheduler = object()
        service._scheduler_task = scheduler

        command = interaction(Message(999))
        await service.post_now(command)

        active = repository.get_active_poll()
        assert active is not None
        assert active.poll_id.startswith("manual:")
        assert active.answers == {}
        assert repository.get_next_run_at() == next_run
        assert repository.is_paused() is True
        assert repository.should_skip_next_run() is True
        assert service._scheduler_task is scheduler
        assert command.response.sent[0][1]["ephemeral"] is True
        assert "投稿したよ" in command.response.sent[0][0][0]
        assert len(audit.sent) == 1
        assert "アンケートを手動投稿" in audit.sent[0]["embed"].description
        assert active.poll_id in audit.sent[0]["embed"].description

    asyncio.run(scenario())


def test_manual_post_closes_previous_poll_and_disables_buttons(tmp_path) -> None:
    async def scenario() -> None:
        public = Channel(10)
        audit = Channel(40)
        previous_message = Message(100)
        public.messages[100] = previous_message
        public.next_id = 101
        service, repository = make_service(tmp_path, public=public, audit=audit)
        prepare_poll(repository)

        await service.post_now(interaction(Message(999)))

        assert previous_message.edits[0]["view"] == ("poll", True)
        active = repository.get_active_poll()
        assert active is not None and active.message_id == 101
        assert repository.get_counts() == {
            "valorant": 0,
            "other_game": 0,
            "work_vc": 0,
        }

    asyncio.run(scenario())


def test_manual_post_save_failure_sends_no_audit(tmp_path, monkeypatch) -> None:
    async def scenario() -> None:
        public = Channel(10)
        audit = Channel(40)
        service, repository = make_service(tmp_path, public=public, audit=audit)
        repository.load()

        def fail_save() -> None:
            raise OSError("private persistence detail")

        monkeypatch.setattr(repository, "save", fail_save)
        command = interaction(Message(999))
        await service.post_now(command)
        assert "投稿できなかった" in command.response.sent[0][0][0]
        assert repository.get_active_poll() is None
        assert not audit.sent

    asyncio.run(scenario())


def test_status_is_read_only_and_reports_active_state(tmp_path, monkeypatch) -> None:
    async def scenario() -> None:
        service, repository = make_service(tmp_path)
        prepare_poll(repository)
        repository.set_answer(7, "valorant")
        repository.set_next_run_at(NOW + timedelta(hours=2))
        repository.set_skip_next_run(True)
        save_calls = 0

        def forbidden_save() -> None:
            nonlocal save_calls
            save_calls += 1

        monkeypatch.setattr(repository, "save", forbidden_save)
        scheduler = object()
        service._scheduler_task = scheduler
        command = interaction(Message(999))

        await service.status(command)

        text = command.response.sent[0][0][0]
        assert "定期投稿：稼働中" in text
        assert "次回のみスキップ：あり" in text
        assert "現在のアンケート：受付中" in text
        assert "Poll ID：poll" in text
        assert "Message ID：100" in text
        assert "🎯 VALORANT 1人" in text
        assert "🎮 その他ゲーム 0人" in text
        assert "🗣️ 作業VC 0人" in text
        assert save_calls == 0
        assert service._scheduler_task is scheduler

    asyncio.run(scenario())


def test_status_reports_paused_without_active_poll(tmp_path) -> None:
    async def scenario() -> None:
        service, repository = make_service(tmp_path)
        repository.load()
        repository.set_paused(True)
        command = interaction(Message(999))
        await service.status(command)
        text = command.response.sent[0][0][0]
        assert "定期投稿：無期限停止中" in text
        assert "次回定期投稿：停止中" in text
        assert "現在のアンケート：なし" in text

    asyncio.run(scenario())


def test_close_current_preserves_schedule_and_audits_once(tmp_path) -> None:
    async def scenario() -> None:
        public = Channel(10)
        audit = Channel(40)
        message = Message(100)
        public.messages[100] = message
        service, repository = make_service(tmp_path, public=public, audit=audit)
        prepare_poll(repository)
        repository.set_answer(7, "work_vc")
        next_run = NOW + timedelta(hours=2)
        repository.set_next_run_at(next_run)
        repository.set_skip_next_run(True)
        scheduler = object()
        service._scheduler_task = scheduler

        first = interaction(Message(999))
        await service.close_current(first)
        active = repository.get_active_poll()
        assert active is not None and active.closed_at == NOW
        assert message.edits[0]["view"] == ("poll", True)
        assert "🐾（1）" in message.edits[0]["embed"].description
        assert repository.get_next_run_at() == next_run
        assert repository.should_skip_next_run() is True
        assert repository.is_paused() is False
        assert service._scheduler_task is scheduler
        assert len(audit.sent) == 1

        second = interaction(Message(999))
        await service.close_current(second)
        assert "すでに締め切られている" in second.response.sent[0][0][0]
        assert len(audit.sent) == 1

    asyncio.run(scenario())


def test_close_current_without_poll_is_safe(tmp_path) -> None:
    async def scenario() -> None:
        audit = Channel(40)
        service, repository = make_service(tmp_path, audit=audit)
        repository.load()
        command = interaction(Message(999))
        await service.close_current(command)
        assert "締め切れるアンケートはない" in command.response.sent[0][0][0]
        assert not audit.sent

    asyncio.run(scenario())


def test_close_save_failure_restores_open_state_and_sends_no_audit(
    tmp_path,
    monkeypatch,
) -> None:
    async def scenario() -> None:
        public = Channel(10)
        public.messages[100] = Message(100)
        audit = Channel(40)
        service, repository = make_service(tmp_path, public=public, audit=audit)
        prepare_poll(repository)

        def fail_save() -> None:
            raise OSError("private persistence detail")

        monkeypatch.setattr(repository, "save", fail_save)
        command = interaction(Message(999))
        await service.close_current(command)
        active = repository.get_active_poll()
        assert active is not None and active.closed_at is None
        assert "締め切れなかった" in command.response.sent[0][0][0]
        assert not audit.sent

    asyncio.run(scenario())
