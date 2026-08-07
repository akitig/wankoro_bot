from pathlib import Path

import pytest

import config as config_module
from config import (
    get_config,
    resolve_runtime_data_dir,
    resolve_runtime_path,
)

RUNTIME_ENV_NAMES = (
    "RUNTIME_DATA_DIR",
    "STATE_DIRECTORY",
    "XDG_DATA_HOME",
    "HOME",
    "VALO_PLAYSTYLE_RESULTS_PATH",
    "OMIKUJI_POINTS_PATH",
    "JOYA_DATA_PATH",
    "XMAS_GACHA_STATE",
    "VALOMAP_BANS_PATH",
    "BUMP_PANEL_STATE_PATH",
    "AVAILABILITY_POLL_STATE_PATH",
)


@pytest.fixture(autouse=True)
def isolated_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    get_config.cache_clear()
    monkeypatch.setattr(config_module, "load_dotenv", lambda: None)
    monkeypatch.setenv("APPLICATION_ID", "1")
    monkeypatch.setenv("GUILD_ID", "1")
    for name in RUNTIME_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    yield
    get_config.cache_clear()


def test_runtime_data_dir_precedence(tmp_path: Path) -> None:
    environ = {
        "RUNTIME_DATA_DIR": str(tmp_path / "runtime"),
        "STATE_DIRECTORY": str(tmp_path / "state"),
        "XDG_DATA_HOME": str(tmp_path / "xdg"),
    }

    assert resolve_runtime_data_dir(environ, tmp_path / "home") == tmp_path / "runtime"
    del environ["RUNTIME_DATA_DIR"]
    assert resolve_runtime_data_dir(environ, tmp_path / "home") == tmp_path / "state"
    del environ["STATE_DIRECTORY"]
    assert resolve_runtime_data_dir(environ, tmp_path / "home") == tmp_path / "xdg" / "wankoro-bot"
    del environ["XDG_DATA_HOME"]
    assert resolve_runtime_data_dir(environ, tmp_path / "home") == (
        tmp_path / "home" / ".local" / "share" / "wankoro-bot"
    )


def test_runtime_data_dir_falls_back_to_current_data_directory(tmp_path: Path) -> None:
    data_dir = tmp_path / "checkout" / "data"

    assert resolve_runtime_data_dir({}, None, data_dir) == data_dir


def test_config_uses_home_fallback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))

    assert get_config().joya_data_path == (
        home / ".local" / "share" / "wankoro-bot" / "2026_joya_state.json"
    )


def test_config_uses_data_fallback_without_home(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("HOME", raising=False)

    assert get_config().joya_data_path == Path("data/2026_joya_state.json")


def test_runtime_data_dir_ignores_empty_values_and_strips_whitespace(tmp_path: Path) -> None:
    environ = {
        "RUNTIME_DATA_DIR": "   ",
        "STATE_DIRECTORY": f"  {tmp_path / 'state'}  ",
    }

    assert resolve_runtime_data_dir(environ, tmp_path / "home") == tmp_path / "state"


def test_state_directory_is_used_as_provided(tmp_path: Path) -> None:
    state_directory = tmp_path / "var" / "lib" / "wankoro-bot"

    resolved = resolve_runtime_data_dir(
        {"STATE_DIRECTORY": str(state_directory)},
        tmp_path / "home",
    )

    assert resolved == state_directory
    assert str(resolved).count("/var/lib/") == 1


@pytest.mark.parametrize(
    ("environment_name", "field_name", "filename"),
    [
        ("OMIKUJI_POINTS_PATH", "omikuji_points_path", "2026_omikujii_points.json"),
        ("JOYA_DATA_PATH", "joya_data_path", "2026_joya_state.json"),
        ("XMAS_GACHA_STATE", "xmas_gacha_state_path", "xmas_gacha_state.json"),
        ("VALOMAP_BANS_PATH", "valomap_bans_path", "valomap_bans.json"),
        (
            "VALO_PLAYSTYLE_RESULTS_PATH",
            "valo_playstyle_results_path",
            "valorant_playstyle_results.json",
        ),
        ("BUMP_PANEL_STATE_PATH", "bump_panel_state_path", "bump_panel_state.json"),
        (
            "AVAILABILITY_POLL_STATE_PATH",
            "availability_poll_state_path",
            "availability_poll_state.json",
        ),
    ],
)
def test_config_runtime_paths_use_root_when_individual_path_is_missing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    environment_name: str,
    field_name: str,
    filename: str,
) -> None:
    runtime_dir = tmp_path / "runtime"
    monkeypatch.setenv("RUNTIME_DATA_DIR", str(runtime_dir))
    monkeypatch.delenv(environment_name, raising=False)

    assert getattr(get_config(), field_name) == runtime_dir / filename


@pytest.mark.parametrize(
    ("environment_name", "field_name"),
    [
        ("OMIKUJI_POINTS_PATH", "omikuji_points_path"),
        ("JOYA_DATA_PATH", "joya_data_path"),
        ("XMAS_GACHA_STATE", "xmas_gacha_state_path"),
        ("VALOMAP_BANS_PATH", "valomap_bans_path"),
        ("VALO_PLAYSTYLE_RESULTS_PATH", "valo_playstyle_results_path"),
        ("BUMP_PANEL_STATE_PATH", "bump_panel_state_path"),
        ("AVAILABILITY_POLL_STATE_PATH", "availability_poll_state_path"),
    ],
)
@pytest.mark.parametrize("absolute", [False, True])
def test_individual_path_overrides_runtime_root_without_changing_path_kind(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    environment_name: str,
    field_name: str,
    absolute: bool,
) -> None:
    explicit_path = tmp_path / "absolute" / "state.json" if absolute else Path(
        "relative/state.json"
    )
    monkeypatch.setenv("RUNTIME_DATA_DIR", str(tmp_path / "runtime"))
    monkeypatch.setenv(environment_name, str(explicit_path))

    assert getattr(get_config(), field_name) == explicit_path


def test_resolve_runtime_path_does_not_create_files(tmp_path: Path) -> None:
    runtime_dir = tmp_path / "not-created"

    resolved = resolve_runtime_path(
        explicit_value=None,
        runtime_dir=runtime_dir,
        filename="state.json",
    )

    assert resolved == runtime_dir / "state.json"
    assert not runtime_dir.exists()


def test_config_creation_has_no_runtime_filesystem_side_effects(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runtime_dir = tmp_path / "not-created"
    monkeypatch.setenv("RUNTIME_DATA_DIR", str(runtime_dir))

    get_config()

    assert not runtime_dir.exists()


@pytest.mark.parametrize(
    ("environment_name", "field_name", "filename"),
    [
        ("OMIKUJI_POINTS_PATH", "omikuji_points_path", "2026_omikujii_points.json"),
        ("JOYA_DATA_PATH", "joya_data_path", "2026_joya_state.json"),
        ("XMAS_GACHA_STATE", "xmas_gacha_state_path", "xmas_gacha_state.json"),
        ("VALOMAP_BANS_PATH", "valomap_bans_path", "valomap_bans.json"),
        (
            "VALO_PLAYSTYLE_RESULTS_PATH",
            "valo_playstyle_results_path",
            "valorant_playstyle_results.json",
        ),
        ("BUMP_PANEL_STATE_PATH", "bump_panel_state_path", "bump_panel_state.json"),
        (
            "AVAILABILITY_POLL_STATE_PATH",
            "availability_poll_state_path",
            "availability_poll_state.json",
        ),
    ],
)
def test_empty_individual_path_uses_runtime_root(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    environment_name: str,
    field_name: str,
    filename: str,
) -> None:
    runtime_dir = tmp_path / "runtime"
    monkeypatch.setenv("RUNTIME_DATA_DIR", str(runtime_dir))
    monkeypatch.setenv(environment_name, "")

    assert getattr(get_config(), field_name) == runtime_dir / filename
