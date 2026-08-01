import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import storage.json_store as json_store
from repositories.bump_panel_repository import BumpPanelRepository


def test_missing_file_loads_defaults_without_creating_file(tmp_path: Path) -> None:
    path = tmp_path / "runtime" / "bump.json"
    repository = BumpPanelRepository(path)

    repository.load()

    assert repository.get_last_bumped_at() is None
    assert repository.get_next_bump_at() is None
    assert repository.get_panel_message_id() == 0
    assert not path.exists()


def test_state_round_trip_uses_aware_iso_datetimes(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "bump.json"
    last = datetime(2026, 8, 1, 1, 2, tzinfo=timezone.utc)
    next_time = last + timedelta(seconds=7200)
    repository = BumpPanelRepository(path)
    repository.set_bump_times(last_bumped_at=last, next_bump_at=next_time)
    repository.set_panel_message_id(123)
    repository.save()

    loaded = BumpPanelRepository(path)
    loaded.load()

    assert loaded.get_last_bumped_at() == last
    assert loaded.get_next_bump_at() == next_time
    assert loaded.get_panel_message_id() == 123
    assert loaded.get_last_bumped_at().utcoffset() == timedelta(0)
    assert json.loads(path.read_text(encoding="utf-8")) == {
        "last_bumped_at": "2026-08-01T01:02:00+00:00",
        "next_bump_at": "2026-08-01T03:02:00+00:00",
        "panel_message_id": 123,
    }


def test_clear_next_bump_at_preserves_other_state(tmp_path: Path) -> None:
    path = tmp_path / "bump.json"
    last = datetime(2026, 8, 1, tzinfo=timezone.utc)
    repository = BumpPanelRepository(path)
    repository.set_bump_times(
        last_bumped_at=last,
        next_bump_at=last + timedelta(hours=2),
    )
    repository.set_panel_message_id(55)
    repository.clear_next_bump_at()
    repository.save()

    state = json.loads(path.read_text(encoding="utf-8"))
    assert state == {
        "last_bumped_at": last.isoformat(),
        "next_bump_at": None,
        "panel_message_id": 55,
    }


@pytest.mark.parametrize("field", ["last_bumped_at", "next_bump_at"])
def test_load_rejects_invalid_datetime_without_overwriting(
    tmp_path: Path,
    field: str,
) -> None:
    path = tmp_path / "bump.json"
    state = {
        "last_bumped_at": None,
        "next_bump_at": None,
        "panel_message_id": 0,
    }
    state[field] = "not-a-date"
    original = json.dumps(state)
    path.write_text(original, encoding="utf-8")

    with pytest.raises(ValueError, match=field):
        BumpPanelRepository(path).load()

    assert path.read_text(encoding="utf-8") == original


def test_load_propagates_invalid_json(tmp_path: Path) -> None:
    path = tmp_path / "bump.json"
    path.write_text("{invalid", encoding="utf-8")

    with pytest.raises(json.JSONDecodeError):
        BumpPanelRepository(path).load()


def test_naive_datetimes_are_rejected(tmp_path: Path) -> None:
    repository = BumpPanelRepository(tmp_path / "bump.json")
    aware = datetime.now(timezone.utc)

    with pytest.raises(ValueError, match="timezone-aware"):
        repository.set_bump_times(
            last_bumped_at=datetime.now(),
            next_bump_at=aware,
        )


def test_atomic_save_failure_preserves_existing_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "bump.json"
    original = '{"sentinel": "日本語"}'
    path.write_text(original, encoding="utf-8")
    repository = BumpPanelRepository(path)
    repository.set_panel_message_id(9)

    def fail_replace(_source: object, _target: object) -> None:
        raise OSError("replace failed")

    monkeypatch.setattr(json_store.os, "replace", fail_replace)
    with pytest.raises(OSError, match="replace failed"):
        repository.save()

    assert path.read_text(encoding="utf-8") == original


def test_repository_exposes_values_not_raw_state(tmp_path: Path) -> None:
    repository = BumpPanelRepository(tmp_path / "bump.json")
    repository.load()

    assert not hasattr(repository, "get_state")
    assert not hasattr(repository, "state")
