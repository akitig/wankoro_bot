"""Completed-result persistence and policy re-evaluation orchestration."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any

from repositories.valorant_playstyle_result_repository import (
    ValorantPlaystyleResultRepository,
)
from services.valorant_playstyle_service import (
    AxisScore,
    PlaystyleCategory,
    PlaystyleClassification,
    PlaystyleScore,
    ValorantPlaystyleService,
)

logger = logging.getLogger(__name__)
UtcNow = Callable[[], datetime]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class ReevaluationChange:
    user_id: int
    old_category: PlaystyleCategory
    new_category: PlaystyleCategory


class ValorantPlaystyleResultService:
    def __init__(
        self,
        core: ValorantPlaystyleService,
        repository: ValorantPlaystyleResultRepository,
        *,
        now: UtcNow = _utc_now,
    ) -> None:
        self.core = core
        self.repository = repository
        self._now = now

    async def save_completed(
        self,
        *,
        user_id: int,
        answers: Mapping[str, str],
        classification: PlaystyleClassification,
        diagnosis_version: str,
        invoked_by: int,
        invoked_by_name: str,
    ) -> dict[str, Any]:
        timestamp = self._now().isoformat()
        record = {
            "user_id": user_id,
            "diagnosis_version": diagnosis_version,
            "completed_at": timestamp,
            "evaluated_at": timestamp,
            "answers": dict(answers),
            "axes": {
                axis: {
                    "score": value.score,
                    "max_score": value.max_score,
                    "normalized": value.normalized,
                }
                for axis, value in classification.score.axes.items()
            },
            "weighted_score": classification.weighted_score,
            "category": classification.category.value,
            "invoked_by": invoked_by,
            "invoked_by_name": invoked_by_name,
        }
        await self.repository.save_result(user_id, record)
        return record

    async def reevaluate_all(
        self, current_diagnosis_version: str
    ) -> tuple[ReevaluationChange, ...]:
        updates: dict[str, dict[str, Any]] = {}
        changes: list[ReevaluationChange] = []
        for user_key, record in self.repository.all_results().items():
            if record["diagnosis_version"] != current_diagnosis_version:
                logger.warning(
                    "Skipping playstyle re-evaluation for user ID %s: diagnosis version mismatch",
                    user_key,
                )
                continue
            score = self._score_from_record(record)
            classification = self.core.classify(score)
            old_category = PlaystyleCategory(record["category"])
            if (
                old_category is classification.category
                and record["weighted_score"] == classification.weighted_score
            ):
                continue
            updates[user_key] = {
                "category": classification.category.value,
                "weighted_score": classification.weighted_score,
                "evaluated_at": self._now().isoformat(),
            }
            changes.append(
                ReevaluationChange(
                    int(user_key), old_category, classification.category
                )
            )
        await self.repository.update_evaluations(updates)
        return tuple(changes)

    @staticmethod
    def _score_from_record(record: Mapping[str, Any]) -> PlaystyleScore:
        axes = {
            axis: AxisScore(
                score=value["score"],
                max_score=value["max_score"],
                normalized=value["normalized"],
            )
            for axis, value in record["axes"].items()
        }
        return PlaystyleScore(
            MappingProxyType(axes),
            tuple(record["answers"]),
            (),
        )
