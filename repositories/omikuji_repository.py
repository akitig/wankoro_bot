"""JSON-backed persistence for the Omikuji feature."""

from __future__ import annotations

import asyncio
from pathlib import Path

from storage.json_store import load_json_or_default, save_json_atomic


class OmikujiRepository:
    """Own and persist Omikuji point state."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = asyncio.Lock()
        self._points: dict[str, int] = {}

    async def load(self) -> None:
        async with self._lock:
            data = load_json_or_default(self._path, {})
            if isinstance(data, dict):
                self._points = {
                    str(key): int(value)
                    for key, value in data.items()
                    if str(key).isdigit()
                }
            else:
                self._points = {}

    async def save(self) -> None:
        async with self._lock:
            save_json_atomic(self._path, self._points)

    async def get_points(self, user_id: int) -> int:
        async with self._lock:
            return int(self._points.get(str(user_id), 0))

    async def ensure_initial(self, user_id: int, initial_points: int) -> int:
        async with self._lock:
            key = str(user_id)
            if key not in self._points:
                self._points[key] = int(initial_points)
            return self._points[key]

    async def add_points(self, user_id: int, delta: int) -> int:
        async with self._lock:
            key = str(user_id)
            points = int(self._points.get(key, 0)) + int(delta)
            if points < 0:
                points = 0
            self._points[key] = points
            return points

    async def consume_points(self, user_id: int, amount: int) -> int:
        return await self.add_points(user_id, -int(amount))

    async def reset_all(self, initial_points: int) -> int:
        async with self._lock:
            keys = list(self._points)
            for key in keys:
                self._points[key] = int(initial_points)
            return len(keys)
