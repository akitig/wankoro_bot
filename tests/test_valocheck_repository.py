import json
from pathlib import Path

import pytest

from repositories.valocheck_repository import ValocheckRepository


def _repository(tmp_path: Path) -> ValocheckRepository:
    return ValocheckRepository(
        completion_path=tmp_path / "runtime" / "completed.json",
        questions_path=tmp_path / "config" / "questions.json",
        intro_path=tmp_path / "config" / "intro.json",
    )


def test_missing_completion_file_starts_empty(tmp_path: Path) -> None:
    repository = _repository(tmp_path)

    repository.load()

    assert repository.has_completion(123) is False


def test_loads_completion_with_string_user_key(tmp_path: Path) -> None:
    path = tmp_path / "runtime" / "completed.json"
    path.parent.mkdir()
    path.write_text('{"123": {"score": 10}}', encoding="utf-8")
    repository = _repository(tmp_path)

    repository.load()

    assert repository.has_completion(123) is True
    assert repository.has_completion(124) is False


def test_saves_completion_and_round_trips_japanese_record(
    tmp_path: Path,
) -> None:
    repository = _repository(tmp_path)
    repository.load()

    repository.save_completion(123, {"result": "エンジョイ", "score": 10})

    saved = json.loads(
        (tmp_path / "runtime" / "completed.json").read_text(encoding="utf-8")
    )
    assert saved == {"123": {"result": "エンジョイ", "score": 10}}
    reloaded = _repository(tmp_path)
    reloaded.load()
    assert reloaded.has_completion(123) is True


def test_save_failure_does_not_damage_existing_file(tmp_path: Path) -> None:
    path = tmp_path / "runtime" / "completed.json"
    path.parent.mkdir()
    original = '{"123": {"score": 1}}\n'
    path.write_text(original, encoding="utf-8")
    repository = _repository(tmp_path)
    repository.load()

    with pytest.raises(TypeError):
        repository.save_completion(456, {"invalid": object()})

    assert path.read_text(encoding="utf-8") == original


def test_loads_raw_questions_and_intro(tmp_path: Path) -> None:
    questions_path = tmp_path / "config" / "questions.json"
    intro_path = tmp_path / "config" / "intro.json"
    questions_path.parent.mkdir()
    questions_path.write_text('[{"q": "質問", "choices": []}]', encoding="utf-8")
    intro_path.write_text('{"title": "題", "text": "本文"}', encoding="utf-8")
    repository = _repository(tmp_path)

    assert repository.load_questions() == [{"q": "質問", "choices": []}]
    assert repository.load_intro() == {"title": "題", "text": "本文"}


def test_missing_questions_and_intro_return_fallback_value(tmp_path: Path) -> None:
    repository = _repository(tmp_path)

    assert repository.load_questions() is None
    assert repository.load_intro() is None


@pytest.mark.parametrize("filename", ["questions.json", "intro.json"])
def test_invalid_optional_json_returns_existing_fallback_value(
    tmp_path: Path, filename: str
) -> None:
    path = tmp_path / "config" / filename
    path.parent.mkdir()
    path.write_text("{broken", encoding="utf-8")
    repository = _repository(tmp_path)

    result = (
        repository.load_questions()
        if filename == "questions.json"
        else repository.load_intro()
    )

    assert result is None


def test_invalid_completion_json_propagates(tmp_path: Path) -> None:
    path = tmp_path / "runtime" / "completed.json"
    path.parent.mkdir()
    path.write_text("{broken", encoding="utf-8")

    with pytest.raises(json.JSONDecodeError):
        _repository(tmp_path).load()
