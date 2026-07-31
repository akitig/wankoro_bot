from pathlib import Path

from config import get_config


def test_config_is_typed_and_cached(monkeypatch) -> None:
    get_config.cache_clear()
    monkeypatch.setenv("APPLICATION_ID", "101")
    monkeypatch.setenv("GUILD_ID", "202")
    monkeypatch.setenv("DISCORD_TOKEN", "private-token")
    monkeypatch.setenv("MANAGER_ROLE_IDS", "1,invalid,2")
    monkeypatch.setenv("VALO_CHECK_DATA_PATH", "runtime/completed.json")
    monkeypatch.setenv("RR_GAME_VALO", "10:20")

    config = get_config()

    assert config is get_config()
    assert config.application_id == 101
    assert config.guild_id == 202
    assert config.manager_role_ids == frozenset({1, 2})
    assert config.valo_check_data_path == Path("runtime/completed.json")
    assert config.reaction_role_values["RR_GAME_VALO"] == "10:20"
    assert "private-token" not in repr(config)

    get_config.cache_clear()
