# Logging architecture

## Design

`logging_config.py` is the single process-wide configuration point. Application
modules obtain their own logger with `logging.getLogger(__name__)`; they do not
add handlers. Reconfiguring the logging layer replaces only handlers owned by
the application, so repeated initialization does not duplicate records.

The default format is:

```text
timestamp level logger-name message
```

Exceptions that affect an operation use `logger.exception(...)`, preserving a
stack trace without including request bodies, JSON data, or Discord message
content. Expected fallback paths may use `DEBUG` with `exc_info=True`.

## Levels and destinations

| Level | Intended use | Destination |
|---|---|---|
| `DEBUG` | Development-only internal flow | stdout / `bot.log` |
| `INFO` | Startup, successful Cog load, command sync, normal operational event | stdout / `bot.log` |
| `WARNING` | Recoverable configuration or external-service condition | stderr / `bot.err` |
| `ERROR` | Failed command, persistence operation, Discord API operation, or Cog setup | stderr / `bot.err` |
| `CRITICAL` | Missing required startup configuration or unrecoverable startup failure | stderr / `bot.err` |

The destinations above rely on the existing systemd Unit. This change does not
modify `StandardOutput`, `StandardError`, or the paths of `bot.log` and
`bot.err`.

## Privacy and secrets

Logs must not contain:

- `DISCORD_TOKEN`, other secrets, or Authorization headers
- `.env` contents
- complete JSON records or runtime state
- DM or message bodies
- answers, scores, nicknames, cooldown state, or other personal runtime data

The configured Discord token is also filtered from formatted log messages as a
last line of defense. Log statements should still be written so that the secret
is never passed to the logger. Discord IDs are omitted unless an incident
cannot be investigated without a narrowly scoped identifier.
