from pathlib import Path

ENV_EXAMPLE = Path(__file__).parents[1] / ".env.example"
EXPECTED_SECTIONS = [
    "Discord",
    "Management",
    "Welcome",
    "Leave Log",
    "DM Forward",
    "Reaction Roles",
    "VALORANT Playstyle Diagnosis",
    "VALORANT Recruit",
    "BUMP",
    "Availability Poll",
    "Xmas Gacha",
    "Joya",
    "Omikuji",
    "Runtime (Optional Override)",
]
REQUIRED_KEYS = {
    "DISCORD_TOKEN",
    "APPLICATION_ID",
    "GUILD_ID",
    "LOG_LEVEL",
    "ADMIN_ID",
    "MANAGER_ROLE_IDS",
    "WELCOME_HANDLER_ROLE_ID",
    "WELCOME_INACTIVE_VOICE_CHANNEL_ID",
    "WELCOME_HANDLER_EXCLUDED_USER_IDS",
    "LEAVE_LOG_CHANNEL_ID",
    "DM_FORWARD_USER_ID",
    "REACTION_ROLE_MESSAGE_IDS",
    "RR_GAME_VALO",
    "RR_GAME_EFT",
    "RR_GAME_SF6",
    "RR_GAME_MONSTER_HUNTER",
    "RR_GAME_OW2",
    "RR_GAME_APEX",
    "RR_V_IRON",
    "RR_V_BRONZE",
    "RR_V_SILVER",
    "RR_V_GOLD",
    "RR_V_PLATINUM",
    "RR_V_DIAMOND",
    "RR_V_ASCENDANT",
    "RR_V_IMMORTAL",
    "RR_V_RADIANT",
    "VALO_PLAYSTYLE_GACHI_MIN",
    "VALO_PLAYSTYLE_NEUTRAL_MIN",
    "VALO_PLAYSTYLE_GACHI_TEAM_MIN",
    "VALO_PLAYSTYLE_GACHI_IMPROVEMENT_MIN",
    "VALO_PLAYSTYLE_GACHI_FOCUS_MIN",
    "VALO_PLAYSTYLE_TIMEOUT_SECONDS",
    "VALO_PLAYSTYLE_TIMEOUT_CHANNEL_ID",
    "VALO_PLAYSTYLE_RESEND_USER_ID",
    "VALO_RECRUIT_CHANNEL_ID",
    "VALO_ROLE_GACHI_ID",
    "VALO_ROLE_ENJOY_ID",
    "VALO_RECRUIT_COOLDOWN_SECONDS",
    "BUMP_CHANNEL_ID",
    "DISBOARD_BOT_ID",
    "DISBOARD_BUMP_COMMAND_ID",
    "BUMP_COOLDOWN_SECONDS",
    "AVAILABILITY_POLL_CHANNEL_ID",
    "AVAILABILITY_POLL_TIMEZONE",
    "AVAILABILITY_POLL_WEEKDAY_WINDOWS",
    "AVAILABILITY_POLL_HOLIDAY_WINDOWS",
    "AVAILABILITY_POLL_AUDIT_GUILD_ID",
    "AVAILABILITY_POLL_AUDIT_CHANNEL_ID",
    "XMAS_GACHA_CHANNEL_ID",
    "XMAS_GACHA_CUTOFF",
    "XMAS_GACHA_CSV",
    "JOYA_CHANNEL_ID",
    "JOYA_WINNER_ROLE_ID",
    "JOYA_MIN_SEC",
    "JOYA_MAX_SEC",
    "OMIKUJI_PANEL_CHANNEL_ID",
    "OMIKUJI_REST_VC_ID",
    "OMIKUJI_RESETTER_USER_ID",
    "RUNTIME_DATA_DIR",
    "JOYA_DATA_PATH",
    "OMIKUJI_POINTS_PATH",
    "XMAS_GACHA_STATE",
    "VALOMAP_BANS_PATH",
    "VALO_PLAYSTYLE_RESULTS_PATH",
    "BUMP_PANEL_STATE_PATH",
    "AVAILABILITY_POLL_STATE_PATH",
}


def _lines() -> list[str]:
    return ENV_EXAMPLE.read_text(encoding="utf-8").splitlines()


def _assignments() -> list[tuple[str, str]]:
    return [
        tuple(line.split("=", 1))
        for line in _lines()
        if line and not line.startswith("#")
    ]


def test_env_example_has_expected_unique_keys() -> None:
    assignments = _assignments()
    keys = [key for key, _value in assignments]

    assert len(keys) == len(set(keys))
    assert set(keys) == REQUIRED_KEYS
    assert not {"ROLE_A", "ROLE_B", "ROLE_C"} & set(keys)


def test_env_example_sections_are_in_required_order() -> None:
    lines = _lines()
    separators = "#" * 50
    sections = [
        lines[index + 1].removeprefix("# ")
        for index, line in enumerate(lines[:-2])
        if line == separators and lines[index + 2] == separators
    ]

    assert sections == EXPECTED_SECTIONS
    assert lines[-1] == "AVAILABILITY_POLL_STATE_PATH="


def test_env_example_preserves_rank_roles_and_has_no_token_value() -> None:
    values = dict(_assignments())
    assert values["DISCORD_TOKEN"] == ""
    assert {key for key in values if key.startswith("RR_V_")} == {
        "RR_V_IRON",
        "RR_V_BRONZE",
        "RR_V_SILVER",
        "RR_V_GOLD",
        "RR_V_PLATINUM",
        "RR_V_DIAMOND",
        "RR_V_ASCENDANT",
        "RR_V_IMMORTAL",
        "RR_V_RADIANT",
    }
