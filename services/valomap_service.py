"""Business logic and state for VALORANT map selection."""

from __future__ import annotations

import logging
import random
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import aiohttp

from repositories.valomap_repository import ValomapRepository

logger = logging.getLogger(__name__)

VALO_API_URL = "https://valorant-api.com/v1/maps"
VALO_API_HEADERS = {
    "User-Agent": "WankoroBot/1.3 (+https://discord.gg/)",
    "Accept": "application/json",
}

MapData = dict[str, Any]
FetchMaps = Callable[[], Awaitable[list[MapData]]]


class ValomapService:
    """Own map and BAN state and perform map-selection business logic."""

    def __init__(
        self,
        *,
        bans_path: Path,
        fetch_maps: FetchMaps | None = None,
    ) -> None:
        self._fetch_maps = fetch_maps or self._fetch_maps_from_api
        self._cached_maps: list[MapData] = []
        self._repository = ValomapRepository(bans_path)
        self.load_bans()

    def load_bans(self) -> None:
        self._repository.load()
        logger.info(
            "VALORANT map bans loaded: count=%d",
            len(self._repository.get_bans()),
        )

    def save_bans(self) -> None:
        try:
            self._repository.save()
            logger.info(
                "VALORANT map bans saved: count=%d",
                len(self._repository.get_bans()),
            )
        except (OSError, TypeError, ValueError):
            logger.exception("Failed to save VALORANT map bans")

    @staticmethod
    async def _fetch_maps_from_api() -> list[MapData]:
        async with aiohttp.ClientSession(headers=VALO_API_HEADERS) as session:
            async with session.get(VALO_API_URL) as response:
                if response.status != 200:
                    logger.warning(
                        "VALORANT map API returned non-success status: %d",
                        response.status,
                    )
                    return []
                data = await response.json()
                return data.get("data", [])

    async def get_comp_maps(self) -> list[MapData]:
        if not self._cached_maps:
            maps = await self._fetch_maps()
            self._cached_maps = [
                map_data
                for map_data in maps
                if (
                    map_data.get("isPlayableInCompetitive", False)
                    or (
                        map_data.get("tacticalDescription")
                        and not map_data["displayName"].startswith("Range")
                    )
                )
            ]
            logger.info("VALORANT maps cached: count=%d", len(self._cached_maps))
        return self._cached_maps

    async def initialize(self) -> None:
        if not self._cached_maps:
            await self.get_comp_maps()

    def is_banned(self, map_name: str) -> bool:
        return map_name in self._repository.get_bans()

    def ban_map(self, map_name: str) -> None:
        self._repository.add_ban(map_name)
        self.save_bans()

    def unban_map(self, map_name: str) -> None:
        self._repository.remove_ban(map_name)
        self.save_bans()

    def clear_bans(self) -> None:
        self._repository.clear_bans()
        self.save_bans()

    async def get_map_listing(self) -> list[tuple[str, bool]]:
        maps = await self.get_comp_maps()
        return [
            (map_data["displayName"], self.is_banned(map_data["displayName"]))
            for map_data in maps
        ]

    async def get_available_maps(self) -> list[MapData]:
        maps = await self.get_comp_maps()
        return [
            map_data
            for map_data in maps
            if not self.is_banned(map_data["displayName"])
        ]

    async def select_random_map(self) -> MapData | None:
        available = await self.get_available_maps()
        if not available:
            return None
        return random.choice(available)
