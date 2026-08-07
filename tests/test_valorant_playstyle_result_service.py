import asyncio
from datetime import datetime, timezone
from pathlib import Path

import pytest

from repositories.valorant_playstyle_result_repository import (
    ValorantPlaystyleResultRepository,
)
from services.valorant_playstyle_result_service import ValorantPlaystyleResultService
from services.valorant_playstyle_service import (
    DEFAULT_CLASSIFICATION_POLICY,
    ClassificationPolicy,
    PlaystyleCategory,
    ValorantPlaystyleService,
)

QUESTION_PATH = Path(__file__).parents[1] / "data" / "valorant_playstyle_questions.json"


def _core(gachi_minimum: float) -> ValorantPlaystyleService:
    policy = ClassificationPolicy(
        weights=DEFAULT_CLASSIFICATION_POLICY.weights,
        gachi_minimum=gachi_minimum,
        neutral_minimum=0.35,
        gachi_axis_minimums=DEFAULT_CLASSIFICATION_POLICY.gachi_axis_minimums,
    )
    return ValorantPlaystyleService(questions_path=QUESTION_PATH, classification_policy=policy)


def _maximum_answers(core: ValorantPlaystyleService) -> dict[str, str]:
    return {
        question.id: max(question.choices, key=lambda choice: sum(choice.scores.values())).id
        for question in core.question_set.questions
    }


def test_completed_result_is_saved_with_all_required_values(tmp_path: Path) -> None:
    core = _core(0.65)
    repository = ValorantPlaystyleResultRepository(tmp_path / "results.json")
    repository.load()
    def now() -> datetime:
        return datetime(2026, 8, 8, tzinfo=timezone.utc)
    service = ValorantPlaystyleResultService(core, repository, now=now)
    answers = _maximum_answers(core)
    classification = core.classify_complete(answers)

    asyncio.run(
        service.save_completed(
            user_id=7,
            answers=answers,
            classification=classification,
            diagnosis_version="2.0",
            invoked_by=9,
            invoked_by_name="admin",
        )
    )

    result = repository.get_result(7)
    assert result["completed_at"] == "2026-08-08T00:00:00+00:00"
    assert result["evaluated_at"] == result["completed_at"]
    assert result["answers"] == answers
    assert len(result["axes"]) == 6
    assert result["category"] == "gachi"


def test_re_evaluation_uses_axes_not_old_category_and_updates_policy_derivatives(
    tmp_path: Path,
) -> None:
    repository = ValorantPlaystyleResultRepository(tmp_path / "results.json")
    repository.load()
    axes = {
        "win": {"score": 5, "max_score": 9, "normalized": 5 / 9},
        "team": {"score": 9, "max_score": 15, "normalized": 9 / 15},
        "improvement": {"score": 5, "max_score": 9, "normalized": 5 / 9},
        "focus": {"score": 5, "max_score": 9, "normalized": 5 / 9},
        "feedback_receive": {"score": 0, "max_score": 3, "normalized": 0.0},
        "feedback_give": {"score": 0, "max_score": 3, "normalized": 0.0},
    }
    asyncio.run(
        repository.save_result(
            7,
            {
                "user_id": 7,
                "diagnosis_version": "2.0",
                "completed_at": "2026-08-08T00:00:00+00:00",
                "evaluated_at": "2026-08-08T00:00:00+00:00",
                "answers": {"q01": "a"},
                "axes": axes,
                "weighted_score": 0.1,
                "category": "enjoy",
                "invoked_by": 9,
                "invoked_by_name": "admin",
            },
        )
    )
    relaxed = ValorantPlaystyleResultService(
        _core(0.55),
        repository,
        now=lambda: datetime(2026, 8, 9, tzinfo=timezone.utc),
    )

    changes = asyncio.run(relaxed.reevaluate_all("2.0"))

    updated = repository.get_result(7)
    assert changes[0].old_category is PlaystyleCategory.ENJOY
    assert changes[0].new_category is PlaystyleCategory.GACHI
    assert updated["category"] == "gachi"
    assert updated["weighted_score"] == pytest.approx(0.5711111111)
    assert updated["evaluated_at"] == "2026-08-09T00:00:00+00:00"


def test_version_mismatch_is_preserved_and_skipped(tmp_path: Path, caplog) -> None:
    core = _core(0.65)
    repository = ValorantPlaystyleResultRepository(tmp_path / "results.json")
    repository.load()
    service = ValorantPlaystyleResultService(core, repository)
    answers = _maximum_answers(core)
    classification = core.classify_complete(answers)
    asyncio.run(
        service.save_completed(
            user_id=7,
            answers=answers,
            classification=classification,
            diagnosis_version="1.0",
            invoked_by=9,
            invoked_by_name="admin",
        )
    )
    before = repository.get_result(7)

    with caplog.at_level("WARNING"):
        changes = asyncio.run(service.reevaluate_all("2.0"))

    assert changes == ()
    assert repository.get_result(7) == before
    assert "version mismatch" in caplog.text
