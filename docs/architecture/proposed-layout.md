# Proposed long-term repository layout

## Goal

Support five or more years of maintenance while preserving all current user
behavior. This document proposes boundaries only; no current file is moved in
this change.

```text
wankorobot/
├── src/
│   └── wankorobot/
│       ├── __init__.py
│       ├── __main__.py
│       ├── bot.py
│       ├── settings.py
│       ├── logging.py
│       ├── cogs/
│       │   ├── community/
│       │   │   ├── welcome.py
│       │   │   ├── leave_log.py
│       │   │   └── dm_forward.py
│       │   ├── roles/
│       │   │   └── reaction_roles.py
│       │   ├── valorant/
│       │   │   ├── maps.py
│       │   │   └── recruit.py
│       │   └── events/
│       │       ├── xmas_2025.py
│       │       ├── joya_2026.py
│       │       └── omikuji_2026.py
│       ├── persistence/
│       │   ├── database.py
│       │   ├── migrations/
│       │   └── repositories/
│       └── services/
│           └── valorant_api.py
├── config/
│   ├── examples/
│   │   └── wankorobot.env.example
│   └── events/
│       └── 2025-xmas/
│           └── rewards.csv
├── deploy/
│   └── systemd/
│       └── wankorobot.service
├── docs/
│   ├── architecture/
│   ├── operations/
│   └── runbooks/
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── fixtures/
│   └── smoke/
├── scripts/
│   ├── backup
│   ├── restore
│   └── validate-config
├── AGENTS.md
├── README.md
├── pyproject.toml
└── requirements.txt
```

Runtime filesystem, deliberately outside Git:

```text
/etc/wankorobot/
└── wankorobot.env

/opt/wankorobot/
├── releases/<version>/
├── current -> releases/<version>/
└── venv/

/var/lib/wankorobot/
├── wankorobot.sqlite3
└── backups/

/var/log/wankorobot/           # only if journald is not used
```

## Boundary rationale

- `src/wankorobot`: importable application package, independent of current
  working directory.
- `config`: reviewed, version-controlled master content only.
- `persistence`: one transactional interface instead of Cog-specific JSON code.
- `services`: external API behavior isolated for timeout, retry, cache, and tests.
- `deploy`: reviewable service templates without embedding secrets.
- `tests`: pure logic tests separated from Discord/API integration tests.
- `/etc`: secrets and deployment-specific IDs.
- `/var/lib`: mutable durable state.
- `/opt`: immutable releases and isolated Python environment.

## Behavior-preserving migration order

1. Add characterization tests around current commands, messages, permissions,
   scoring, probabilities, cooldowns, and JSON semantics.
2. Introduce typed settings while preserving all current environment names and
   defaults.
3. Centralize command/view registration without renaming commands or custom IDs.
4. Add persistence interfaces backed by the current JSON files.
5. Move runtime paths outside the worktree using environment variables.
6. Migrate runtime state to SQLite with verified one-time import and rollback.
7. Move modules into `src/` in small groups, keeping extension names mapped
   during transition.
8. Adopt a new Python virtual environment separately from any discord.py update.
9. Switch systemd only after offline and sandbox-guild acceptance tests.

Each step should be independently deployable and reversible. The old runtime
data must remain read-only until the new deployment has passed its rollback
window.
