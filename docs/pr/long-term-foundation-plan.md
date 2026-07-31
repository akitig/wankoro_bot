# PR: Establish a five-year maintenance foundation without behavior changes

## Summary

This proposed pull request adds dependency metadata, repository guidance,
ignore rules, and architecture documentation. It deliberately makes no Python
application-code changes and moves no production data.

## Changes

- Pin the currently observed production runtime dependencies.
- Add project/tool configuration for future tests, linting, typing, and coverage.
- Add repository-wide production-safety instructions.
- Expand ignore rules for secrets, Python/tool output, virtual environments,
  logs, temporary files, and mutable runtime state.
- Classify every current JSON/CSV/environment/log file.
- Propose a long-term source, configuration, deployment, test, and runtime
  filesystem layout.

## Non-goals

- No Discord command, message, permission, score, probability, or cooldown change.
- No Python/Cog change.
- No data migration or deletion.
- No dependency installation or upgrade.
- No systemd edit or restart.
- No commit or push.

## Risk

Low for runtime behavior: the running process does not consume the new metadata
or documentation. `.gitignore` does not affect already tracked files, so the
existing runtime JSON remains tracked until a later, controlled migration.

The main review decision is whether exact production versions should be kept in
both `requirements.txt` and `pyproject.toml`. This proposal does so to make the
current baseline explicit; a later tooling PR may generate one from the other.

## Validation

- Confirm no `main.py` or `cogs/*.py` diff.
- Parse `pyproject.toml`.
- Verify `.env.sample` remains trackable.
- Verify secrets, caches, logs, runtime state, and temporary files are ignored.
- Confirm the existing modified runtime JSON files remain untouched.

## Follow-up PR sequence

1. Characterization tests and config validation.
2. Dedicated virtual environment and reproducible deployment template.
3. Command synchronization and logging refactor.
4. Runtime-data path separation with backup/rollback.
5. SQLite migration.
6. Python upgrade, followed separately by discord.py upgrade.
