"""JSON-backed persistence for the Xmas gacha feature."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from storage.json_store import load_json_or_default, save_json_atomic

STATE_NONE = "__NONE__"


class XmasRepository:
    """Own and persist Xmas runtime state."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._state: dict[str, Any] = {
            "orig_nick": {},
            "panel_message_id": 0,
        }

    def load(self) -> None:
        state = load_json_or_default(
            self._path,
            {"orig_nick": {}, "panel_message_id": 0},
        )
        if "orig_nick" not in state or not isinstance(state["orig_nick"], dict):
            state["orig_nick"] = {}
        if "panel_message_id" not in state:
            state["panel_message_id"] = 0
        self._state = state

    def save(self) -> None:
        save_json_atomic(self._path, self._state)

    def get_original_nickname(self, guild_id: int, user_id: int) -> str | None:
        guild_state = self._state.get("orig_nick", {}).get(str(guild_id), {})
        value = guild_state.get(str(user_id))
        if value is None:
            return None
        if value == STATE_NONE:
            return STATE_NONE
        if isinstance(value, str):
            return value
        return None

    def save_original_nickname(
        self,
        guild_id: int,
        user_id: int,
        nickname: str | None,
    ) -> bool:
        if self.get_original_nickname(guild_id, user_id) is not None:
            return False
        original_nicknames = self._state.setdefault("orig_nick", {})
        guild_state = original_nicknames.setdefault(str(guild_id), {})
        guild_state[str(user_id)] = STATE_NONE if nickname is None else nickname
        return True

    def delete_original_nickname(self, guild_id: int, user_id: int) -> bool:
        original_nicknames = self._state.setdefault("orig_nick", {})
        guild_state = original_nicknames.setdefault(str(guild_id), {})
        return guild_state.pop(str(user_id), None) is not None

    def get_original_user_ids(self, guild_id: int) -> list[int]:
        guild_state = self._state.get("orig_nick", {}).get(str(guild_id), {})
        user_ids: list[int] = []
        for user_id in guild_state:
            try:
                user_ids.append(int(user_id))
            except ValueError:
                continue
        return user_ids

    def get_panel_message_id(self) -> int:
        return int(self._state.get("panel_message_id", 0) or 0)

    def set_panel_message_id(self, message_id: int) -> None:
        self._state["panel_message_id"] = message_id
