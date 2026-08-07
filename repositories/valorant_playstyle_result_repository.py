"""Atomic JSON persistence for completed VALORANT playstyle diagnoses."""

from __future__ import annotations

import asyncio
import copy
from collections.abc import Mapping
from math import isclose
from pathlib import Path
from typing import Any

from storage.json_store import load_json_or_default, save_json_atomic

RESULT_SCHEMA_VERSION = 1
RESULT_CATEGORIES = {"enjoy", "neutral", "gachi"}
RESULT_AXES = {
    "win",
    "team",
    "improvement",
    "focus",
    "feedback_receive",
    "feedback_give",
}


class ResultValidationError(ValueError):
    """Raised when persisted diagnosis results have an invalid schema."""


def _validate_record(user_key: str, record: Any) -> None:
    if not user_key.isdigit() or not isinstance(record, dict):
        raise ResultValidationError("result keys must be user IDs with object values")
    if record.get("user_id") != int(user_key):
        raise ResultValidationError(f"result {user_key} has mismatched user_id")
    for key in ("diagnosis_version", "completed_at", "evaluated_at"):
        if not isinstance(record.get(key), str) or not record[key]:
            raise ResultValidationError(f"result {user_key}.{key} must be a string")
    if record.get("category") not in RESULT_CATEGORIES:
        raise ResultValidationError(f"result {user_key}.category is invalid")
    weighted_score = record.get("weighted_score")
    if (
        isinstance(weighted_score, bool)
        or not isinstance(weighted_score, int | float)
        or not 0.0 <= weighted_score <= 1.0
    ):
        raise ResultValidationError(
            f"result {user_key}.weighted_score must be between 0.0 and 1.0"
        )
    answers = record.get("answers")
    if not isinstance(answers, dict) or not all(
        isinstance(question_id, str) and isinstance(choice_id, str)
        for question_id, choice_id in answers.items()
    ):
        raise ResultValidationError(f"result {user_key}.answers must be an object")
    axes = record.get("axes")
    if not isinstance(axes, dict) or set(axes) != RESULT_AXES:
        raise ResultValidationError(f"result {user_key}.axes must contain all axes")
    for axis, value in axes.items():
        if not isinstance(value, dict):
            raise ResultValidationError(f"result {user_key}.axes.{axis} must be an object")
        if isinstance(value.get("score"), bool) or not isinstance(value.get("score"), int):
            raise ResultValidationError(f"result {user_key}.axes.{axis}.score must be int")
        if isinstance(value.get("max_score"), bool) or not isinstance(
            value.get("max_score"), int
        ):
            raise ResultValidationError(
                f"result {user_key}.axes.{axis}.max_score must be int"
            )
        normalized = value.get("normalized")
        if isinstance(normalized, bool) or not isinstance(normalized, int | float):
            raise ResultValidationError(
                f"result {user_key}.axes.{axis}.normalized must be numeric"
            )
        if value["score"] < 0 or value["max_score"] < 0:
            raise ResultValidationError(
                f"result {user_key}.axes.{axis} scores must be non-negative"
            )
        if value["score"] > value["max_score"] or not 0.0 <= normalized <= 1.0:
            raise ResultValidationError(
                f"result {user_key}.axes.{axis} values are out of range"
            )
        expected = value["score"] / value["max_score"] if value["max_score"] else 0.0
        if not isclose(normalized, expected):
            raise ResultValidationError(
                f"result {user_key}.axes.{axis}.normalized is inconsistent"
            )
    invoked_by = record.get("invoked_by")
    if invoked_by is not None and not isinstance(invoked_by, int):
        raise ResultValidationError(f"result {user_key}.invoked_by must be int or null")
    invoked_by_name = record.get("invoked_by_name")
    if invoked_by_name is not None and not isinstance(invoked_by_name, str):
        raise ResultValidationError(
            f"result {user_key}.invoked_by_name must be string or null"
        )


def validate_result_data(data: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(data, dict) or data.get("schema_version") != RESULT_SCHEMA_VERSION:
        raise ResultValidationError(f"schema_version must be {RESULT_SCHEMA_VERSION}")
    results = data.get("results")
    if not isinstance(results, dict):
        raise ResultValidationError("results must be an object")
    for user_key, record in results.items():
        _validate_record(user_key, record)
    return copy.deepcopy(results)


class ValorantPlaystyleResultRepository:
    """Keep completed results in memory and serialize updates under one lock."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._results: dict[str, dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    def load(self) -> None:
        data = load_json_or_default(
            self._path,
            {"schema_version": RESULT_SCHEMA_VERSION, "results": {}},
        )
        self._results = validate_result_data(data)

    def get_result(self, user_id: int) -> dict[str, Any] | None:
        result = self._results.get(str(user_id))
        return copy.deepcopy(result) if result is not None else None

    def all_results(self) -> dict[str, dict[str, Any]]:
        return copy.deepcopy(self._results)

    async def save_result(self, user_id: int, record: Mapping[str, Any]) -> None:
        candidate = copy.deepcopy(dict(record))
        _validate_record(str(user_id), candidate)
        async with self._lock:
            updated = copy.deepcopy(self._results)
            updated[str(user_id)] = candidate
            self._save(updated)
            self._results = updated

    async def update_evaluations(
        self, updates: Mapping[str, Mapping[str, Any]]
    ) -> None:
        if not updates:
            return
        async with self._lock:
            updated = copy.deepcopy(self._results)
            for user_key, values in updates.items():
                if user_key not in updated:
                    raise KeyError(user_key)
                updated[user_key].update(copy.deepcopy(dict(values)))
                _validate_record(user_key, updated[user_key])
            self._save(updated)
            self._results = updated

    def _save(self, results: Mapping[str, Mapping[str, Any]]) -> None:
        save_json_atomic(
            self._path,
            {"schema_version": RESULT_SCHEMA_VERSION, "results": results},
        )
