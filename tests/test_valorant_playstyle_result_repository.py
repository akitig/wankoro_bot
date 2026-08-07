import asyncio
import json
from pathlib import Path

import pytest

from repositories.valorant_playstyle_result_repository import (
    ResultValidationError,
    ValorantPlaystyleResultRepository,
)

AXES = ("win", "team", "improvement", "focus", "feedback_receive", "feedback_give")


def _record(user_id: int, category: str = "neutral") -> dict:
    return {
        "user_id": user_id,
        "diagnosis_version": "2.0",
        "completed_at": "2026-08-08T00:00:00+00:00",
        "evaluated_at": "2026-08-08T00:00:00+00:00",
        "answers": {"q01": "a"},
        "axes": {
            axis: {"score": 1, "max_score": 3, "normalized": 1 / 3}
            for axis in AXES
        },
        "weighted_score": 1 / 3,
        "category": category,
        "invoked_by": 99,
        "invoked_by_name": "admin",
    }


def test_save_round_trip_contains_source_facts_and_derived_values(tmp_path: Path) -> None:
    path = tmp_path / "runtime" / "results.json"
    repository = ValorantPlaystyleResultRepository(path)
    repository.load()

    asyncio.run(repository.save_result(1, _record(1)))

    saved = json.loads(path.read_text(encoding="utf-8"))
    result = saved["results"]["1"]
    assert saved["schema_version"] == 1
    assert result["answers"] == {"q01": "a"}
    assert result["diagnosis_version"] == "2.0"
    assert set(result["axes"]) == set(AXES)
    assert result["weighted_score"] == pytest.approx(1 / 3)
    assert result["category"] == "neutral"
    assert result["invoked_by"] == 99


def test_replacing_one_user_preserves_other_users(tmp_path: Path) -> None:
    repository = ValorantPlaystyleResultRepository(tmp_path / "results.json")
    repository.load()
    asyncio.run(repository.save_result(1, _record(1)))
    asyncio.run(repository.save_result(2, _record(2)))
    replacement = _record(1, "gachi")

    asyncio.run(repository.save_result(1, replacement))

    assert repository.get_result(1)["category"] == "gachi"
    assert repository.get_result(2)["category"] == "neutral"


def test_concurrent_updates_do_not_lose_users(tmp_path: Path) -> None:
    repository = ValorantPlaystyleResultRepository(tmp_path / "results.json")
    repository.load()

    async def save_both() -> None:
        await asyncio.gather(
            repository.save_result(1, _record(1)),
            repository.save_result(2, _record(2)),
        )

    asyncio.run(save_both())

    assert set(repository.all_results()) == {"1", "2"}


def test_malformed_json_and_schema_are_not_silently_reset(tmp_path: Path) -> None:
    malformed = tmp_path / "malformed.json"
    malformed.write_text("{broken", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        ValorantPlaystyleResultRepository(malformed).load()

    invalid = tmp_path / "invalid.json"
    invalid.write_text('{"schema_version": 1, "results": []}', encoding="utf-8")
    with pytest.raises(ResultValidationError):
        ValorantPlaystyleResultRepository(invalid).load()


def test_legacy_category_and_inconsistent_axis_score_are_rejected(tmp_path: Path) -> None:
    repository = ValorantPlaystyleResultRepository(tmp_path / "results.json")
    repository.load()

    with pytest.raises(ResultValidationError, match="category"):
        asyncio.run(repository.save_result(1, _record(1, "balanced")))

    inconsistent = _record(1)
    inconsistent["axes"]["team"]["normalized"] = 0.9
    with pytest.raises(ResultValidationError, match="inconsistent"):
        asyncio.run(repository.save_result(1, inconsistent))


def test_failed_atomic_save_keeps_previous_memory_and_file(monkeypatch, tmp_path: Path) -> None:
    path = tmp_path / "results.json"
    repository = ValorantPlaystyleResultRepository(path)
    repository.load()
    asyncio.run(repository.save_result(1, _record(1)))
    original = path.read_text(encoding="utf-8")

    def fail_save(*args, **kwargs):
        raise OSError("failed")

    monkeypatch.setattr(
        "repositories.valorant_playstyle_result_repository.save_json_atomic",
        fail_save,
    )
    with pytest.raises(OSError):
        asyncio.run(repository.save_result(2, _record(2)))

    assert repository.get_result(2) is None
    assert path.read_text(encoding="utf-8") == original
