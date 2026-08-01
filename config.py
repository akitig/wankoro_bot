"""Typed application configuration loaded once from the process environment."""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

PRODUCTION_DATA_DIR = Path("/home/akitig/Desktop/Bot/Toureikai/Wankorobot/data")


def resolve_runtime_data_dir(
    environ: Mapping[str, str],
    home: Path | None,
    data_dir: Path = Path("data"),
) -> Path:
    """Resolve the directory containing mutable application state."""

    for name in ("RUNTIME_DATA_DIR", "STATE_DIRECTORY"):
        value = environ.get(name)
        if value is not None and value.strip():
            return Path(value.strip())

    xdg_data_home = environ.get("XDG_DATA_HOME")
    if xdg_data_home is not None and xdg_data_home.strip():
        return Path(xdg_data_home.strip()) / "wankoro-bot"
    if home is not None:
        return home / ".local" / "share" / "wankoro-bot"
    return data_dir


def resolve_runtime_path(
    *,
    explicit_value: str | None,
    runtime_dir: Path,
    filename: str,
    strip: bool = False,
) -> Path:
    """Prefer an explicitly configured path, otherwise use ``runtime_dir``."""

    if explicit_value is not None:
        value = explicit_value.strip() if strip else explicit_value
        if value:
            return Path(value)
    return runtime_dir / filename


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


def _positive_int_with_default(name: str, default: int) -> int:
    value = _int_with_default(name, default)
    return value if value > 0 else default


def _string_with_default(name: str, default: str, *, strip: bool = False) -> str:
    value = os.getenv(name)
    if value is None or (not strip and not value) or (strip and not value.strip()):
        return default
    return value.strip() if strip else value


def _required_int(name: str) -> int:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing environment variable: {name}")
    return int(value)


def _id_set(name: str) -> frozenset[int]:
    value = os.getenv(name, "")
    return frozenset(int(item) for item in value.split(",") if item.strip().isdigit())


def _strict_optional_id(name: str) -> int | None:
    value = os.getenv(name)
    if value is None or not value.strip():
        return None
    try:
        parsed = int(value.strip())
    except ValueError as error:
        raise ValueError(f"{name} must be a positive integer") from error
    if parsed <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return parsed


def _strict_id_set(name: str) -> frozenset[int]:
    value = os.getenv(name, "")
    parsed: set[int] = set()
    for item in value.split(","):
        stripped = item.strip()
        if not stripped:
            continue
        try:
            identifier = int(stripped)
        except ValueError as error:
            raise ValueError(f"{name} must contain positive integer IDs") from error
        if identifier <= 0:
            raise ValueError(f"{name} must contain positive integer IDs")
        parsed.add(identifier)
    return frozenset(parsed)


def _reaction_role_values() -> Mapping[str, str]:
    values = {
        key: value
        for key, value in os.environ.items()
        if key.startswith("RR_")
    }
    return MappingProxyType(values)


def parse_time_windows(value: str) -> tuple[str, ...]:
    """Validate, de-duplicate, and order same-day ``HH:MM-HH:MM`` windows."""

    parts = value.split(",")
    if not parts or any(not part.strip() for part in parts):
        raise ValueError("availability poll windows must not contain empty entries")
    parsed: set[tuple[int, int]] = set()
    for part in parts:
        bounds = part.strip().split("-")
        if len(bounds) != 2:
            raise ValueError("availability poll windows must use HH:MM-HH:MM")
        minutes: list[int] = []
        for bound in bounds:
            pieces = bound.strip().split(":")
            if len(pieces) != 2 or any(len(piece) != 2 for piece in pieces):
                raise ValueError("availability poll times must use HH:MM")
            if not all(piece.isdigit() for piece in pieces):
                raise ValueError("availability poll times must be numeric")
            hour, minute = map(int, pieces)
            if not 0 <= hour <= 23 or not 0 <= minute <= 59:
                raise ValueError("availability poll time is out of range")
            minutes.append(hour * 60 + minute)
        start, end = minutes
        if end <= start:
            raise ValueError("availability poll window end must follow start")
        parsed.add((start, end))
    ordered = sorted(parsed)
    for previous, current in zip(ordered, ordered[1:], strict=False):
        if current[0] < previous[1]:
            raise ValueError("availability poll windows must not overlap")
    return tuple(
        f"{start // 60:02d}:{start % 60:02d}-{end // 60:02d}:{end % 60:02d}"
        for start, end in ordered
    )


def _timezone_name(name: str, default: str) -> str:
    value = _string_with_default(name, default, strip=True)
    try:
        ZoneInfo(value)
    except ZoneInfoNotFoundError as error:
        raise ValueError("invalid availability poll timezone") from error
    return value


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
    welcome_handler_role_id: int | None
    welcome_inactive_voice_channel_id: int | None
    welcome_handler_excluded_user_ids: frozenset[int]
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

    bump_channel_id: int | None
    disboard_bot_id: int | None
    disboard_bump_command_id: int | None
    bump_cooldown_seconds: int
    bump_panel_state_path: Path

    availability_poll_channel_id: int | None
    availability_poll_timezone: str
    availability_poll_weekday_windows: tuple[str, ...]
    availability_poll_holiday_windows: tuple[str, ...]
    availability_poll_state_path: Path
    availability_poll_audit_guild_id: int | None
    availability_poll_audit_channel_id: int | None

    def require_id(self, value: int | None, environment_name: str) -> int:
        """Return a required Cog setting or fail when that Cog is constructed."""

        if value is None:
            raise RuntimeError(f"Missing environment variable: {environment_name}")
        return value


def _load_config() -> Config:
    load_dotenv()
    home_value = os.environ.get("HOME")
    home = Path(home_value.strip()) if home_value and home_value.strip() else None
    runtime_data_dir = resolve_runtime_data_dir(os.environ, home)
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
        welcome_handler_role_id=_strict_optional_id("WELCOME_HANDLER_ROLE_ID"),
        welcome_inactive_voice_channel_id=_strict_optional_id(
            "WELCOME_INACTIVE_VOICE_CHANNEL_ID"
        ),
        welcome_handler_excluded_user_ids=_strict_id_set(
            "WELCOME_HANDLER_EXCLUDED_USER_IDS"
        ),
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
        xmas_gacha_state_path=resolve_runtime_path(
            explicit_value=os.getenv("XMAS_GACHA_STATE"),
            runtime_dir=runtime_data_dir,
            filename="xmas_gacha_state.json",
            strip=True,
        ),
        xmas_gacha_channel_id=_int_with_default("XMAS_GACHA_CHANNEL_ID", 0),
        xmas_gacha_cutoff=_string_with_default(
            "XMAS_GACHA_CUTOFF",
            "2025-12-26T07:00:00+09:00",
            strip=True,
        ),
        joya_data_path=resolve_runtime_path(
            explicit_value=os.getenv("JOYA_DATA_PATH"),
            runtime_dir=runtime_data_dir,
            filename="2026_joya_state.json",
        ),
        joya_min_sec=_int_with_default("JOYA_MIN_SEC", 60),
        joya_max_sec=_int_with_default("JOYA_MAX_SEC", 300),
        joya_winner_role_id=_int_with_default("JOYA_WINNER_ROLE_ID", 0),
        joya_channel_id=_int_with_default("JOYA_CHANNEL_ID", 0),
        omikuji_points_path=resolve_runtime_path(
            explicit_value=os.getenv("OMIKUJI_POINTS_PATH"),
            runtime_dir=runtime_data_dir,
            filename="2026_omikujii_points.json",
            strip=True,
        ),
        omikuji_rest_vc_id=_int_with_default("OMIKUJI_REST_VC_ID", 0),
        omikuji_resetter_user_id=_int_with_default("OMIKUJI_RESETTER_USER_ID", 0),
        omikuji_panel_channel_id=_int_with_default("OMIKUJI_PANEL_CHANNEL_ID", 0),
        valomap_bans_path=resolve_runtime_path(
            explicit_value=os.getenv("VALOMAP_BANS_PATH"),
            runtime_dir=runtime_data_dir,
            filename="valomap_bans.json",
        ),
        valo_check_data_path=resolve_runtime_path(
            explicit_value=os.getenv("VALO_CHECK_DATA_PATH"),
            runtime_dir=runtime_data_dir,
            filename="valo_check_completed.json",
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
        bump_channel_id=_optional_int("BUMP_CHANNEL_ID"),
        disboard_bot_id=_optional_int("DISBOARD_BOT_ID"),
        disboard_bump_command_id=_optional_int("DISBOARD_BUMP_COMMAND_ID"),
        bump_cooldown_seconds=_positive_int_with_default(
            "BUMP_COOLDOWN_SECONDS",
            7200,
        ),
        bump_panel_state_path=resolve_runtime_path(
            explicit_value=os.getenv("BUMP_PANEL_STATE_PATH"),
            runtime_dir=runtime_data_dir,
            filename="bump_panel_state.json",
            strip=True,
        ),
        availability_poll_channel_id=_optional_int("AVAILABILITY_POLL_CHANNEL_ID"),
        availability_poll_timezone=_timezone_name(
            "AVAILABILITY_POLL_TIMEZONE",
            "Asia/Tokyo",
        ),
        availability_poll_weekday_windows=parse_time_windows(
            _string_with_default(
                "AVAILABILITY_POLL_WEEKDAY_WINDOWS",
                "20:00-21:00",
                strip=True,
            )
        ),
        availability_poll_holiday_windows=parse_time_windows(
            _string_with_default(
                "AVAILABILITY_POLL_HOLIDAY_WINDOWS",
                "13:00-14:00,20:00-21:00",
                strip=True,
            )
        ),
        availability_poll_state_path=resolve_runtime_path(
            explicit_value=os.getenv("AVAILABILITY_POLL_STATE_PATH"),
            runtime_dir=runtime_data_dir,
            filename="availability_poll_state.json",
            strip=True,
        ),
        availability_poll_audit_guild_id=_optional_int(
            "AVAILABILITY_POLL_AUDIT_GUILD_ID"
        ),
        availability_poll_audit_channel_id=_optional_int(
            "AVAILABILITY_POLL_AUDIT_CHANNEL_ID"
        ),
    )


@lru_cache(maxsize=1)
def get_config() -> Config:
    """Return the process-wide immutable Config instance."""

    return _load_config()
