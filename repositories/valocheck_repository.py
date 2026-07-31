"""JSON persistence for the VALORANT role diagnostic."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from storage.json_store import load_json, load_json_or_default, save_json_atomic


class ValocheckRepository:
    """Own the diagnostic's persistent completion and raw configuration data."""

    def __init__(
        self,
        *,
        completion_path: Path,
        questions_path: Path,
        intro_path: Path,
    ) -> None:
        self._completion_path = completion_path
        self._questions_path = questions_path
        self._intro_path = intro_path
        self._completions: dict[str, Any] = {}

    def load(self) -> None:
        """Load completion records, defaulting only when the file is absent."""

        self._completions = load_json_or_default(self._completion_path, {})

    def has_completion(self, member_id: int) -> bool:
        return str(member_id) in self._completions

    def save_completion(
        self,
        member_id: int,
        completion: Mapping[str, object],
    ) -> None:
        self._completions[str(member_id)] = dict(completion)
        save_json_atomic(self._completion_path, self._completions)

    def load_questions(self) -> object | None:
        return self._load_optional(self._questions_path)

    def load_intro(self) -> object | None:
        return self._load_optional(self._intro_path)

    @staticmethod
    def _load_optional(path: Path) -> object | None:
        try:
            return load_json(path)
        except (OSError, json.JSONDecodeError):
            return None
