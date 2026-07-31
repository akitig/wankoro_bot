"""Typed application configuration loaded once from the process environment."""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

PRODUCTION_DATA_DIR = Path("/home/akitig/Desktop/Bot/Toureikai/Wankorobot/data")


def _optional_int(name: str) -> int | None:
    value = os.getenv(name)
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _int_with_default(name: str, default: int) -> int:
    value = os.getenv(name)
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _string_with_default(name: str, default: str, *, strip: bool = False) -> str:
    value = os.getenv(name)
    if value is None or (not strip and not value) or (strip and not value.strip()):
        return default
    return value.strip() if strip else value


def _string_if_missing(name: str, default: str) -> str:
    value = os.getenv(name)
    return default if value is None else value


def _required_int(name: str) -> int:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing environment variable: {name}")
    return int(value)


def _id_set(name: str) -> frozenset[int]:
    value = os.getenv(name, "")
    return frozenset(int(item) for item in value.split(",") if item.strip().isdigit())


def _reaction_role_values() -> Mapping[str, str]:
    values = {
        key: value
        for key, value in os.environ.items()
        if key.startswith("RR_")
    }
    return MappingProxyType(values)


@dataclass(frozen=True)
class Config:
    discord_token: str | None = field(repr=False)
    application_id: int
    guild_id: int
    log_level: str

    admin_id: int | None
    manager_role_ids: frozenset[int]
    welcome_role_a: int | None
    welcome_role_b: int | None
    welcome_role_c: int | None
    leave_log_channel_id: int | None
    dm_forward_user_id: int | None

    reaction_role_message_ids: frozenset[int]
    reaction_role_values: Mapping[str, str] = field(repr=False)

    xmas_gacha_csv_path: Path
    xmas_gacha_state_path: Path
    xmas_gacha_channel_id: int
    xmas_gacha_cutoff: str

    joya_data_path: Path
    joya_min_sec: int
    joya_max_sec: int
    joya_winner_role_id: int
    joya_channel_id: int

    omikuji_points_path: Path
    omikuji_rest_vc_id: int
    omikuji_resetter_user_id: int
    omikuji_panel_channel_id: int

    valomap_bans_path: Path
    valo_check_data_path: Path
    valo_check_questions_path: Path
    valo_check_intro_path: Path
    valo_role_enjoy_id: int | None
    valo_role_gachi_id: int | None
    valo_role_log_channel_id: int | None
    valo_check_view_timeout_sec: int
    valo_check_thresh_enjoy_only: int
    valo_check_thresh_gachi_only: int
    valo_check_label_enjoy: str
    valo_check_label_gachi: str
    valo_check_label_both: str

    valo_recruit_channel_id: int | None
    valo_recruit_gachi_role_id: int | None
    valo_recruit_enjoy_role_id: int | None
    valo_recruit_cooldown_seconds: int

    def require_id(self, value: int | None, environment_name: str) -> int:
        """Return a required Cog setting or fail when that Cog is constructed."""

        if value is None:
            raise RuntimeError(f"Missing environment variable: {environment_name}")
        return value


def _load_config() -> Config:
    load_dotenv()
    return Config(
        discord_token=os.getenv("DISCORD_TOKEN"),
        application_id=_required_int("APPLICATION_ID"),
        guild_id=_required_int("GUILD_ID"),
        log_level=_string_with_default("LOG_LEVEL", "INFO", strip=True),
        admin_id=_optional_int("ADMIN_ID"),
        manager_role_ids=_id_set("MANAGER_ROLE_IDS"),
        welcome_role_a=_optional_int("ROLE_A"),
        welcome_role_b=_optional_int("ROLE_B"),
        welcome_role_c=_optional_int("ROLE_C"),
        leave_log_channel_id=_optional_int("LEAVE_LOG_CHANNEL_ID"),
        dm_forward_user_id=_optional_int("DM_FORWARD_USER_ID"),
        reaction_role_message_ids=_id_set("REACTION_ROLE_MESSAGE_IDS"),
        reaction_role_values=_reaction_role_values(),
        xmas_gacha_csv_path=Path(
            _string_with_default(
                "XMAS_GACHA_CSV",
                str(PRODUCTION_DATA_DIR / "2025_xmas_gacha.csv"),
                strip=True,
            )
        ),
        xmas_gacha_state_path=Path(
            _string_with_default(
                "XMAS_GACHA_STATE",
                str(PRODUCTION_DATA_DIR / "xmas_gacha_state.json"),
                strip=True,
            )
        ),
        xmas_gacha_channel_id=_int_with_default("XMAS_GACHA_CHANNEL_ID", 0),
        xmas_gacha_cutoff=_string_with_default(
            "XMAS_GACHA_CUTOFF",
            "2025-12-26T07:00:00+09:00",
            strip=True,
        ),
        joya_data_path=Path(_string_if_missing("JOYA_DATA_PATH", "./data/joya_state.json")),
        joya_min_sec=_int_with_default("JOYA_MIN_SEC", 60),
        joya_max_sec=_int_with_default("JOYA_MAX_SEC", 300),
        joya_winner_role_id=_int_with_default("JOYA_WINNER_ROLE_ID", 0),
        joya_channel_id=_int_with_default("JOYA_CHANNEL_ID", 0),
        omikuji_points_path=Path(
            _string_with_default(
                "OMIKUJI_POINTS_PATH",
                "data/2026_omikujii_points.json",
                strip=True,
            )
        ),
        omikuji_rest_vc_id=_int_with_default("OMIKUJI_REST_VC_ID", 0),
        omikuji_resetter_user_id=_int_with_default("OMIKUJI_RESETTER_USER_ID", 0),
        omikuji_panel_channel_id=_int_with_default("OMIKUJI_PANEL_CHANNEL_ID", 0),
        valomap_bans_path=Path("valomap_bans.json"),
        valo_check_data_path=Path(
            _string_with_default(
                "VALO_CHECK_DATA_PATH",
                "data/valo_check_completed.json",
            )
        ),
        valo_check_questions_path=Path(
            _string_with_default(
                "VALO_CHECK_QUESTIONS_PATH",
                "data/valo_questions.json",
            )
        ),
        valo_check_intro_path=Path(
            _string_with_default(
                "VALO_CHECK_INTRO_PATH",
                "data/valo_intro.json",
            )
        ),
        valo_role_enjoy_id=_optional_int("ROLE_ENJOY_ID"),
        valo_role_gachi_id=_optional_int("ROLE_GACHI_ID"),
        valo_role_log_channel_id=_optional_int("VALO_ROLE_LOG_CHANNEL_ID"),
        valo_check_view_timeout_sec=_int_with_default(
            "VALO_CHECK_VIEW_TIMEOUT_SEC",
            1800,
        ),
        valo_check_thresh_enjoy_only=_int_with_default(
            "VALO_CHECK_THRESH_ENJOY_ONLY",
            6,
        ),
        valo_check_thresh_gachi_only=_int_with_default(
            "VALO_CHECK_THRESH_GACHI_ONLY",
            12,
        ),
        valo_check_label_enjoy=_string_with_default(
            "VALO_CHECK_LABEL_ENJOY",
            "ENJOYのみ",
        ),
        valo_check_label_gachi=_string_with_default(
            "VALO_CHECK_LABEL_GACHI",
            "GACHIのみ",
        ),
        valo_check_label_both=_string_with_default(
            "VALO_CHECK_LABEL_BOTH",
            "GACHI+ENJOY",
        ),
        valo_recruit_channel_id=_optional_int("VALO_RECRUIT_CHANNEL_ID"),
        valo_recruit_gachi_role_id=_optional_int("VALO_ROLE_GACHI_ID"),
        valo_recruit_enjoy_role_id=_optional_int("VALO_ROLE_ENJOY_ID"),
        valo_recruit_cooldown_seconds=_int_with_default(
            "VALO_RECRUIT_COOLDOWN_SECONDS",
            300,
        ),
    )


@lru_cache(maxsize=1)
def get_config() -> Config:
    """Return the process-wide immutable Config instance."""

    return _load_config()
