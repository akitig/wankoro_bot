# AGENTS.md

## Scope

These instructions apply to the entire repository.

## Production safety

- This repository is deployed as a production Discord Bot managed by systemd.
- Do not restart, stop, enable, disable, or reload the service unless the user
  explicitly requests it.
- Do not commit, push, pull, switch branches, or alter remotes unless explicitly
  requested.
- Never print, copy, commit, or modify `.env` values or Discord credentials.
- Treat files containing Discord user IDs, answers, scores, nicknames, cooldowns,
  and game state as private runtime data.
- Preserve existing user changes. In particular, do not overwrite JSON files
  that the running Bot may be updating.

## Change discipline

- Keep user-visible commands, command names, component `custom_id` values,
  permissions, messages, scoring, probabilities, cooldowns, and persistence
  semantics unchanged unless a functional change is explicitly requested.
- Separate infrastructure, refactoring, dependency, Python, and discord.py
  upgrades into reviewable changes.
- Do not combine a Python-version upgrade with a discord.py upgrade.
- Add or update tests before behavior-preserving refactors.
- Use atomic writes and explicit validation for persistent state.
- Avoid broad exception handling without logging the exception and context.
- Register application commands and persistent views in lifecycle hooks intended
  to run once; do not add registration work to reconnecting `on_ready` handlers.

## Validation

For changes that do not require Discord connectivity, run the relevant subset:

```bash
python -m compileall -q main.py cogs
python -m pytest
python -m ruff check .
python -m mypy
```

If a tool or dependency is not installed, report that fact; do not install into
the system Python automatically. Never start `main.py` against the production
token as a validation step.

## Data classification

- Version-controlled configuration/master data belongs under `config/`.
- Mutable runtime state belongs under a deployment-owned data directory and
  must not be committed.
- Secrets belong in the deployment environment or an external secret store,
  never in Git.
- Generated logs, caches, coverage files, virtual environments, and temporary
  atomic-write files must remain untracked.
- See `docs/architecture/runtime-data.md` for the current classification and
  proposed migration boundaries.

## Documentation

- Keep `README.md`, `.env.example`, dependency files, the systemd template, and
  runtime-data documentation consistent with the implementation.
- Mark facts that cannot be verified as unknown rather than guessing.
