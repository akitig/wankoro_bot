# Configuration boundary

## Loading and lifetime

`config.py` is the only active application module that reads environment
variables or calls `load_dotenv()`. `get_config()` creates one immutable,
process-wide `Config` instance. The Discord token is excluded from the Config
representation.

`main.py` uses Config only as the process bootstrap for logging, application ID,
Guild ID, and the Discord token. Each Cog then calls `get_config()` at its
composition boundary and passes only the values required by its Service.
Service and Repository modules do not import `Config` or call `get_config()`.

Existing environment names and defaults remain unchanged. Application and
Guild IDs are required when Config is first loaded. Settings required by only
one Cog remain optional in Config and are validated when that Cog is
constructed, so a missing Cog-specific setting does not prevent unrelated Cogs
from being attempted.

## Layer boundaries

```text
environment / .env
        ↓
     config.py
        ↓
main.py bootstrap + Cog composition
        ↓
Service constructor values
        ↓
Repository Path values
```

- **Config** owns environment names, parsing, defaults, immutability, and the
  process-wide cached configuration instance.
- **Cog** obtains Config, validates Cog-specific required values, and injects
  primitive IDs, paths, timeouts, cooldowns, labels, and factories into its
  Service.
- **Service** accepts only the settings it uses. It does not know environment
  variable names and does not retain the application-wide Config object.
- **Repository** receives only the `Path` or paths needed for persistence. It
  does not import Config or read environment variables.

This explicit composition boundary makes dependencies visible in constructor
signatures. Tests can construct Services with small values and `tmp_path`
without patching global Config. A future dependency-injection mechanism can
replace the Cog composition code without changing Service business logic or
Repository APIs; a DI container is not needed for the current application.

## Environment variables

| Area | Environment variables |
|---|---|
| Discord process | `DISCORD_TOKEN`, `APPLICATION_ID`, `GUILD_ID`, `LOG_LEVEL` |
| Welcome and moderation | `ADMIN_ID`, `MANAGER_ROLE_IDS`, `ROLE_A`, `ROLE_B`, `ROLE_C`, `WELCOME_HANDLER_ROLE_ID`, `WELCOME_INACTIVE_VOICE_CHANNEL_ID`, `WELCOME_HANDLER_EXCLUDED_USER_IDS`, `LEAVE_LOG_CHANNEL_ID`, `DM_FORWARD_USER_ID` |
| Reaction Roles | `REACTION_ROLE_MESSAGE_IDS`, every `RR_*` mapping |
| Runtime storage | `RUNTIME_DATA_DIR`, systemd-provided `STATE_DIRECTORY`, `XDG_DATA_HOME` |
| VALORANT check | `ROLE_ENJOY_ID`, `ROLE_GACHI_ID`, `VALO_ROLE_LOG_CHANNEL_ID`, `VALO_CHECK_VIEW_TIMEOUT_SEC`, `VALO_CHECK_DATA_PATH`, `VALOMAP_BANS_PATH`, `VALO_CHECK_QUESTIONS_PATH`, `VALO_CHECK_INTRO_PATH`, `VALO_CHECK_THRESH_ENJOY_ONLY`, `VALO_CHECK_THRESH_GACHI_ONLY`, `VALO_CHECK_LABEL_ENJOY`, `VALO_CHECK_LABEL_GACHI`, `VALO_CHECK_LABEL_BOTH` |
| VALORANT recruit | `VALO_RECRUIT_CHANNEL_ID`, `VALO_ROLE_GACHI_ID`, `VALO_ROLE_ENJOY_ID`, `VALO_RECRUIT_COOLDOWN_SECONDS` |
| Christmas event | `XMAS_GACHA_CSV`, `XMAS_GACHA_STATE`, `XMAS_GACHA_CHANNEL_ID`, `XMAS_GACHA_CUTOFF` |
| New Year bell event | `JOYA_DATA_PATH`, `JOYA_MIN_SEC`, `JOYA_MAX_SEC`, `JOYA_WINNER_ROLE_ID`, `JOYA_CHANNEL_ID` |
| Omikuji event | `OMIKUJI_POINTS_PATH`, `OMIKUJI_REST_VC_ID`, `OMIKUJI_RESETTER_USER_ID`, `OMIKUJI_PANEL_CHANNEL_ID` |
| DISBOARD BUMP panel | `BUMP_CHANNEL_ID`, `DISBOARD_BOT_ID`, `DISBOARD_BUMP_COMMAND_ID`, `BUMP_COOLDOWN_SECONDS`, `BUMP_PANEL_STATE_PATH` |
| Availability poll | `AVAILABILITY_POLL_CHANNEL_ID`, `AVAILABILITY_POLL_TIMEZONE`, `AVAILABILITY_POLL_WEEKDAY_WINDOWS`, `AVAILABILITY_POLL_HOLIDAY_WINDOWS`, `AVAILABILITY_POLL_STATE_PATH`, `AVAILABILITY_POLL_AUDIT_GUILD_ID`, `AVAILABILITY_POLL_AUDIT_CHANNEL_ID` |

Mutable runtime paths use an explicitly configured feature path first. Otherwise,
their root is resolved in this order: `RUNTIME_DATA_DIR`, `STATE_DIRECTORY`,
`XDG_DATA_HOME/wankoro-bot`, `~/.local/share/wankoro-bot`, then the existing
working-directory-relative `data/` directory when no home is available. Empty
root values are ignored and surrounding whitespace is removed.
`STATE_DIRECTORY` is the absolute path supplied by systemd and is used directly;
Config does not rebuild it below `/var/lib`.

Existing feature-specific path whitespace behavior is preserved. Omikuji and
Xmas paths are stripped; Joya and VALORANT check paths remain literal. An empty
feature path is treated as unset. `VALOMAP_BANS_PATH` provides the same override
for Valomap while retaining relative paths as working-directory-relative.

## Runtime and master-data paths

All JSON and CSV paths exposed through Config use `pathlib.Path`.

| Config field | Runtime-root filename |
|---|---|
| `valomap_bans_path` | `valomap_bans.json` |
| `valo_check_data_path` | `valo_check_completed.json` |
| `valo_check_questions_path` | `data/valo_questions.json` |
| `valo_check_intro_path` | `data/valo_intro.json` |
| `xmas_gacha_csv_path` | `/home/akitig/Desktop/Bot/Toureikai/Wankorobot/data/2025_xmas_gacha.csv` |
| `xmas_gacha_state_path` | `xmas_gacha_state.json` |
| `joya_data_path` | `2026_joya_state.json` |
| `omikuji_points_path` | `2026_omikujii_points.json` |
| `bump_panel_state_path` | `bump_panel_state.json` |
| `availability_poll_state_path` | `availability_poll_state.json` |

Availability windows use comma-separated same-day `HH:MM-HH:MM` values. Config
strips whitespace, removes exact duplicates, sorts by start time, and rejects
empty, malformed, reversed, or overlapping windows. The default timezone is
`Asia/Tokyo`. Japanese public holidays are evaluated locally with `jpholiday`
1.0.2 (MIT); no external holiday API is called.

Resolving Config paths only constructs `Path` values. It does not create the
runtime directory or any JSON file.

## Logging

`LOG_LEVEL` controls the process-wide minimum level and defaults to `INFO`.
Accepted standard names include `DEBUG`, `INFO`, `WARNING`, `ERROR`, and
`CRITICAL`. An empty or invalid value safely falls back to `INFO`.

`logging_config.py` configures logging once during application startup. Records
through `INFO` go to stdout, while `WARNING` and above go to stderr. This keeps
the existing systemd `StandardOutput`/`StandardError` destinations usable
without changing the Unit. The Discord token is registered as a secret and
redacted if it is accidentally included in a log message.
