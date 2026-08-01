from pathlib import Path

import pytest

import config as config_module
from config import get_config


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
    monkeypatch.delenv("VALO_ROLE_LOG_CHANNEL_ID", raising=False)

    config = get_config()

    assert config.dm_forward_user_id is None
    assert config.valo_role_log_channel_id is None


def test_config_is_typed_and_cached(monkeypatch) -> None:
    monkeypatch.setenv("APPLICATION_ID", "101")
    monkeypatch.setenv("GUILD_ID", "202")
    monkeypatch.setenv("DISCORD_TOKEN", "private-token")
    monkeypatch.setenv("MANAGER_ROLE_IDS", "1,invalid,2")
    monkeypatch.setenv("VALO_CHECK_DATA_PATH", "runtime/completed.json")
    monkeypatch.setenv("RR_GAME_VALO", "10:20")
    monkeypatch.delenv("LOG_LEVEL", raising=False)

    config = get_config()

    assert config is get_config()
    assert config.application_id == 101
    assert config.guild_id == 202
    assert config.manager_role_ids == frozenset({1, 2})
    assert config.valo_check_data_path == Path("runtime/completed.json")
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
