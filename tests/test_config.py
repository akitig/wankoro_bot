from pathlib import Path

import pytest

import config as config_module
from config import get_config, parse_time_windows


@pytest.fixture(autouse=True)
def clear_config_cache():
    get_config.cache_clear()
    yield
    get_config.cache_clear()


def test_required_application_id_is_rejected_when_missing(monkeypatch) -> None:
    monkeypatch.setattr(config_module, "load_dotenv", lambda: None)
    monkeypatch.delenv("APPLICATION_ID", raising=False)
    monkeypatch.setenv("GUILD_ID", "202")

    with pytest.raises(RuntimeError, match="APPLICATION_ID"):
        get_config()


def test_optional_ids_are_none_when_unset(monkeypatch) -> None:
    monkeypatch.setenv("APPLICATION_ID", "101")
    monkeypatch.setenv("GUILD_ID", "202")
    monkeypatch.delenv("DM_FORWARD_USER_ID", raising=False)

    config = get_config()

    assert config.dm_forward_user_id is None


def test_welcome_handler_config_values_are_typed(monkeypatch) -> None:
    monkeypatch.setenv("APPLICATION_ID", "101")
    monkeypatch.setenv("GUILD_ID", "202")
    monkeypatch.setenv("WELCOME_HANDLER_ROLE_ID", "1451758143636901960")
    monkeypatch.setenv("WELCOME_INACTIVE_VOICE_CHANNEL_ID", "940190873101172746")
    monkeypatch.setenv(
        "WELCOME_HANDLER_EXCLUDED_USER_IDS",
        " 780783001218842655, ,123456789012345678,780783001218842655 ",
    )

    config = get_config()

    assert config.welcome_handler_role_id == 1451758143636901960
    assert config.welcome_inactive_voice_channel_id == 940190873101172746
    assert config.welcome_handler_excluded_user_ids == frozenset(
        {780783001218842655, 123456789012345678}
    )
    assert isinstance(config.welcome_handler_excluded_user_ids, frozenset)


def test_welcome_handler_optional_config_defaults(monkeypatch) -> None:
    monkeypatch.setenv("APPLICATION_ID", "101")
    monkeypatch.setenv("GUILD_ID", "202")
    monkeypatch.delenv("WELCOME_HANDLER_ROLE_ID", raising=False)
    monkeypatch.delenv("WELCOME_INACTIVE_VOICE_CHANNEL_ID", raising=False)
    monkeypatch.setenv("WELCOME_HANDLER_EXCLUDED_USER_IDS", "")

    config = get_config()

    assert config.welcome_handler_role_id is None
    assert config.welcome_inactive_voice_channel_id is None
    assert config.welcome_handler_excluded_user_ids == frozenset()


def test_retired_welcome_role_config_is_absent(monkeypatch) -> None:
    monkeypatch.setenv("APPLICATION_ID", "101")
    monkeypatch.setenv("GUILD_ID", "202")
    monkeypatch.setenv("ROLE_A", "1")
    monkeypatch.setenv("ROLE_B", "2")
    monkeypatch.setenv("ROLE_C", "3")

    config = get_config()

    assert not hasattr(config, "welcome_role_a")
    assert not hasattr(config, "welcome_role_b")
    assert not hasattr(config, "welcome_role_c")


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("WELCOME_HANDLER_ROLE_ID", "invalid"),
        ("WELCOME_INACTIVE_VOICE_CHANNEL_ID", "-1"),
        ("WELCOME_HANDLER_EXCLUDED_USER_IDS", "123,invalid"),
    ],
)
def test_invalid_welcome_handler_ids_are_rejected(monkeypatch, name, value) -> None:
    monkeypatch.setenv("APPLICATION_ID", "101")
    monkeypatch.setenv("GUILD_ID", "202")
    monkeypatch.setenv(name, value)

    with pytest.raises(ValueError, match=name):
        get_config()


def test_config_is_typed_and_cached(monkeypatch) -> None:
    monkeypatch.setenv("APPLICATION_ID", "101")
    monkeypatch.setenv("GUILD_ID", "202")
    monkeypatch.setenv("DISCORD_TOKEN", "private-token")
    monkeypatch.setenv("MANAGER_ROLE_IDS", "1,invalid,2")
    monkeypatch.setenv("RR_GAME_VALO", "10:20")
    monkeypatch.delenv("LOG_LEVEL", raising=False)

    config = get_config()

    assert config is get_config()
    assert config.application_id == 101
    assert config.guild_id == 202
    assert config.manager_role_ids == frozenset({1, 2})
    assert config.reaction_role_values["RR_GAME_VALO"] == "10:20"
    assert config.log_level == "INFO"
    assert "private-token" not in repr(config)


def test_bump_panel_config_values(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("APPLICATION_ID", "101")
    monkeypatch.setenv("GUILD_ID", "202")
    monkeypatch.setenv("BUMP_CHANNEL_ID", "1432640140911575060")
    monkeypatch.setenv("DISBOARD_BOT_ID", "302050872383242240")
    monkeypatch.setenv("DISBOARD_BUMP_COMMAND_ID", "947088344167366698")
    monkeypatch.setenv("BUMP_COOLDOWN_SECONDS", "3600")
    monkeypatch.setenv("RUNTIME_DATA_DIR", str(tmp_path))

    config = get_config()

    assert config.bump_channel_id == 1432640140911575060
    assert config.disboard_bot_id == 302050872383242240
    assert config.disboard_bump_command_id == 947088344167366698
    assert config.bump_cooldown_seconds == 3600
    assert config.bump_panel_state_path == tmp_path / "bump_panel_state.json"


def test_bump_panel_optional_command_and_cooldown_fallback(monkeypatch) -> None:
    monkeypatch.setenv("APPLICATION_ID", "101")
    monkeypatch.setenv("GUILD_ID", "202")
    monkeypatch.delenv("DISBOARD_BUMP_COMMAND_ID", raising=False)
    monkeypatch.setenv("BUMP_COOLDOWN_SECONDS", "0")

    config = get_config()

    assert config.disboard_bump_command_id is None
    assert config.bump_cooldown_seconds == 7200


def test_availability_poll_config(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("APPLICATION_ID", "101")
    monkeypatch.setenv("GUILD_ID", "202")
    monkeypatch.setenv("AVAILABILITY_POLL_CHANNEL_ID", "10")
    monkeypatch.setenv("AVAILABILITY_POLL_AUDIT_GUILD_ID", "30")
    monkeypatch.setenv("AVAILABILITY_POLL_AUDIT_CHANNEL_ID", "40")
    monkeypatch.setenv("AVAILABILITY_POLL_TIMEZONE", "Asia/Tokyo")
    monkeypatch.setenv(
        "AVAILABILITY_POLL_WEEKDAY_WINDOWS",
        " 22:00-23:00 , 19:30-20:15 ",
    )
    monkeypatch.setenv("AVAILABILITY_POLL_HOLIDAY_WINDOWS", "12:00-13:30")
    monkeypatch.setenv("RUNTIME_DATA_DIR", str(tmp_path))

    config = get_config()

    assert config.availability_poll_channel_id == 10
    assert config.availability_poll_audit_guild_id == 30
    assert config.availability_poll_audit_channel_id == 40
    assert config.availability_poll_timezone == "Asia/Tokyo"
    assert config.availability_poll_weekday_windows == (
        "19:30-20:15",
        "22:00-23:00",
    )
    assert config.availability_poll_holiday_windows == ("12:00-13:30",)
    assert config.availability_poll_state_path == tmp_path / "availability_poll_state.json"


def test_availability_poll_defaults(monkeypatch) -> None:
    monkeypatch.setenv("APPLICATION_ID", "101")
    monkeypatch.setenv("GUILD_ID", "202")
    for name in (
        "AVAILABILITY_POLL_TIMEZONE",
        "AVAILABILITY_POLL_WEEKDAY_WINDOWS",
        "AVAILABILITY_POLL_HOLIDAY_WINDOWS",
    ):
        monkeypatch.delenv(name, raising=False)

    config = get_config()

    assert config.availability_poll_timezone == "Asia/Tokyo"
    assert config.availability_poll_weekday_windows == ("20:00-21:00",)
    assert config.availability_poll_holiday_windows == (
        "13:00-14:00",
        "20:00-21:00",
    )


def test_invalid_availability_poll_config_is_rejected(monkeypatch) -> None:
    monkeypatch.setenv("APPLICATION_ID", "101")
    monkeypatch.setenv("GUILD_ID", "202")
    monkeypatch.setenv("AVAILABILITY_POLL_WEEKDAY_WINDOWS", "20:00-19:00")
    with pytest.raises(ValueError):
        get_config()

    assert parse_time_windows("20:00-21:00") == ("20:00-21:00",)
