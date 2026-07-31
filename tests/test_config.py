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
