"""JSON-backed persistence for the Joya bell feature."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from storage.json_store import load_json_or_default, save_json_atomic


class JoyaRepository:
    """Own and persist Joya guild and user state."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._data: dict[str, Any] = load_json_or_default(
            path,
            {"guilds": {}, "users": {}},
        )

    def save(self) -> None:
        save_json_atomic(self._path, self._data)

    def get_guild(self, guild_id: int) -> dict[str, Any]:
        guilds = self._data.setdefault("guilds", {})
        return guilds.setdefault(str(guild_id), {})

    def get_user(self, guild_id: int, user_id: int) -> dict[str, Any]:
        users = self._data.setdefault("users", {})
        return users.setdefault(f"{guild_id}:{user_id}", {})

    def reset_guild_users(self, guild_id: int) -> int:
        guilds = self._data.setdefault("guilds", {})
        guilds[str(guild_id)] = {}
        users = self._data.setdefault("users", {})
        prefix = f"{guild_id}:"
        keys = [key for key in users if key.startswith(prefix)]
        for key in keys:
            del users[key]
        self.save()
        return len(keys)
