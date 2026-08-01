import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import storage.json_store as json_store
from repositories.availability_poll_repository import AvailabilityPollRepository

NOW = datetime(2026, 8, 1, 11, 0, tzinfo=timezone.utc)


def test_missing_file_has_defaults_without_creation(tmp_path: Path) -> None:
    path = tmp_path / "runtime" / "poll.json"
    repository = AvailabilityPollRepository(path)
    repository.load()
    assert repository.get_active_poll() is None
    assert repository.get_next_run_at() is None
    assert repository.is_paused() is False
    assert repository.should_skip_next_run() is False
    assert not path.exists()


def test_legacy_state_adds_scheduler_defaults(tmp_path: Path) -> None:
    path = tmp_path / "poll.json"
    path.write_text('{"active_poll": null, "next_run_at": null}', encoding="utf-8")
    repository = AvailabilityPollRepository(path)
    repository.load()
    assert repository.is_paused() is False
    assert repository.should_skip_next_run() is False


def test_poll_answers_controls_and_datetimes_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "poll.json"
    repository = AvailabilityPollRepository(path)
    repository.load()
    repository.create_poll(
        poll_id=NOW.isoformat(),
        message_id=100,
        channel_id=200,
        opened_at=NOW,
    )
    assert repository.set_answer(1, "valorant") is None
    assert repository.set_answer(1, "valorant") == "valorant"
    assert repository.set_answer(1, "work_vc") == "valorant"
    assert repository.set_answer(2, "other_game") is None
    repository.set_next_run_at(NOW + timedelta(days=1))
    repository.set_paused(True)
    repository.set_skip_next_run(True)
    repository.save()

    loaded = AvailabilityPollRepository(path)
    loaded.load()
    active = loaded.get_active_poll()
    assert active is not None
    assert active.poll_id == NOW.isoformat()
    assert active.message_id == 100
    assert active.channel_id == 200
    assert active.opened_at == NOW
    assert active.answers == {"1": "work_vc", "2": "other_game"}
    assert loaded.get_counts() == {"valorant": 0, "other_game": 1, "work_vc": 1}
    assert loaded.get_next_run_at() == NOW + timedelta(days=1)
    assert loaded.is_paused() is True
    assert loaded.should_skip_next_run() is True
    assert loaded.remove_answer(1) == "work_vc"
    assert loaded.remove_answer(1) is None


def test_close_poll_and_returned_answers_are_immutable(tmp_path: Path) -> None:
    repository = AvailabilityPollRepository(tmp_path / "poll.json")
    repository.load()
    repository.create_poll(
        poll_id="poll",
        message_id=1,
        channel_id=2,
        opened_at=NOW,
    )
    repository.set_answer(3, "valorant")
    active = repository.get_active_poll()
    assert active is not None
    with pytest.raises(TypeError):
        active.answers["4"] = "work_vc"  # type: ignore[index]
    repository.close_active_poll(NOW + timedelta(hours=1))
    assert repository.get_active_poll().closed_at == NOW + timedelta(hours=1)  # type: ignore[union-attr]


@pytest.mark.parametrize("answer", ["", "invalid", "VALORANT"])
def test_rejects_unsupported_answers(tmp_path: Path, answer: str) -> None:
    repository = AvailabilityPollRepository(tmp_path / "poll.json")
    repository.load()
    repository.create_poll(
        poll_id="poll",
        message_id=1,
        channel_id=2,
        opened_at=NOW,
    )
    with pytest.raises(ValueError, match="unsupported"):
        repository.set_answer(1, answer)


def test_rejects_naive_datetimes(tmp_path: Path) -> None:
    repository = AvailabilityPollRepository(tmp_path / "poll.json")
    repository.load()
    with pytest.raises(ValueError, match="timezone-aware"):
        repository.set_next_run_at(datetime.now())
    with pytest.raises(ValueError, match="timezone-aware"):
        repository.create_poll(
            poll_id="poll",
            message_id=1,
            channel_id=2,
            opened_at=datetime.now(),
        )


@pytest.mark.parametrize(
    "content",
    ["{invalid", "[]", '{"active_poll": {}}', '{"is_paused": 1}'],
)
def test_invalid_json_or_schema_is_not_overwritten(tmp_path: Path, content: str) -> None:
    path = tmp_path / "poll.json"
    path.write_text(content, encoding="utf-8")
    repository = AvailabilityPollRepository(path)
    with pytest.raises((json.JSONDecodeError, ValueError)):
        repository.load()
    assert path.read_text(encoding="utf-8") == content


def test_atomic_failure_preserves_existing_file(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "poll.json"
    original = json.dumps(
        {
            "active_poll": None,
            "next_run_at": None,
            "is_paused": False,
            "skip_next_run": False,
        }
    )
    path.write_text(original, encoding="utf-8")
    repository = AvailabilityPollRepository(path)
    repository.load()
    repository.set_paused(True)

    def fail(_source, _target) -> None:
        raise OSError("replace failed")

    monkeypatch.setattr(json_store.os, "replace", fail)
    with pytest.raises(OSError):
        repository.save()
    assert path.read_text(encoding="utf-8") == original
