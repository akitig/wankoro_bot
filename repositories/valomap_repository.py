"""JSON-backed persistence for VALORANT map bans."""

from __future__ import annotations

from pathlib import Path

from storage.json_store import load_json_or_default, save_json_atomic


class ValomapRepository:
    """Own and persist the set of banned VALORANT map names."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._bans: set[str] = set()

    def load(self) -> None:
        data = load_json_or_default(self._path, {"bans": []})
        self._bans = set(data.get("bans", []))

    def save(self) -> None:
        save_json_atomic(self._path, {"bans": list(self._bans)})

    def get_bans(self) -> set[str]:
        return set(self._bans)

    def add_ban(self, map_name: str) -> bool:
        previous_count = len(self._bans)
        self._bans.add(map_name)
        return len(self._bans) != previous_count

    def remove_ban(self, map_name: str) -> bool:
        if map_name not in self._bans:
            return False
        self._bans.remove(map_name)
        return True

    def clear_bans(self) -> bool:
        if not self._bans:
            return False
        self._bans.clear()
        return True
