"""JSON-backed persistence for the DISBOARD BUMP panel."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from storage.json_store import load_json_or_default, save_json_atomic

INITIAL_STATE: dict[str, Any] = {
    "last_bumped_at": None,
    "next_bump_at": None,
    "panel_message_id": 0,
}


def _parse_datetime(value: object, field_name: str) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a timezone-aware ISO 8601 string")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"{field_name} contains an invalid datetime") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return parsed


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


class BumpPanelRepository:
    """Own and persist BUMP cooldown and panel identity state."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._state: dict[str, Any] = dict(INITIAL_STATE)

    def load(self) -> None:
        state = load_json_or_default(self._path, INITIAL_STATE)
        if not isinstance(state, dict):
            raise ValueError("BUMP panel state must be a JSON object")

        last_bumped_at = _parse_datetime(
            state.get("last_bumped_at"),
            "last_bumped_at",
        )
        next_bump_at = _parse_datetime(
            state.get("next_bump_at"),
            "next_bump_at",
        )
        panel_message_id = state.get("panel_message_id", 0)
        if isinstance(panel_message_id, bool) or not isinstance(panel_message_id, int):
            raise ValueError("panel_message_id must be an integer")
        if panel_message_id < 0:
            raise ValueError("panel_message_id must not be negative")

        self._state = {
            "last_bumped_at": (
                last_bumped_at.isoformat() if last_bumped_at is not None else None
            ),
            "next_bump_at": (
                next_bump_at.isoformat() if next_bump_at is not None else None
            ),
            "panel_message_id": panel_message_id,
        }

    def save(self) -> None:
        save_json_atomic(self._path, self._state)

    def get_last_bumped_at(self) -> datetime | None:
        return _parse_datetime(self._state["last_bumped_at"], "last_bumped_at")

    def get_next_bump_at(self) -> datetime | None:
        return _parse_datetime(self._state["next_bump_at"], "next_bump_at")

    def get_panel_message_id(self) -> int:
        return int(self._state["panel_message_id"])

    def set_bump_times(
        self,
        *,
        last_bumped_at: datetime,
        next_bump_at: datetime,
    ) -> None:
        _require_aware(last_bumped_at, "last_bumped_at")
        _require_aware(next_bump_at, "next_bump_at")
        if next_bump_at < last_bumped_at:
            raise ValueError("next_bump_at must not precede last_bumped_at")
        self._state["last_bumped_at"] = last_bumped_at.isoformat()
        self._state["next_bump_at"] = next_bump_at.isoformat()

    def clear_next_bump_at(self) -> None:
        self._state["next_bump_at"] = None

    def set_panel_message_id(self, message_id: int) -> None:
        if (
            isinstance(message_id, bool)
            or not isinstance(message_id, int)
            or message_id < 0
        ):
            raise ValueError("panel_message_id must be a non-negative integer")
        self._state["panel_message_id"] = message_id
