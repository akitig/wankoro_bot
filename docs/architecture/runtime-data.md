# Runtime data and configuration classification

## Purpose

This document classifies the repository's current data without moving files or
changing Bot behavior. The target layout is a migration proposal, not the
current production layout.

## Classification rules

| Class | Definition | Git policy | Backup policy |
|---|---|---|---|
| Secret | Token or deployment credential | Never commit | Encrypted/restricted |
| Deployment configuration | Environment-specific IDs, paths, thresholds | Commit examples only | Back up actual values securely |
| Master configuration | Reviewed content/rules that define behavior | Commit | Git history is primary |
| Runtime state | Bot/user state mutated during operation | Never commit | Consistent scheduled snapshots |
| Log/generated | Replaceable output and caches | Never commit | Rotate; retain only as required |
| Historical source | Inactive code retained for reference | Commit or archive by policy | Git history |

## Current files

| Current path | Class | Mutated by Bot | Contains private data | Current Git state | Proposed destination |
|---|---|---:|---:|---|---|
| `.env` | Secret + deployment configuration | No | Yes | Ignored | External secret store or `/etc/wankorobot/wankorobot.env` |
| `.env.example` | Configuration example | No | No values | Tracked | `config/examples/wankorobot.env.example` |
| `data/valo_questions.json` | Master configuration | No | No known user state | Tracked | `config/valocheck/questions.json` |
| `data/valo_intro.json` | Master configuration | No | No known user state | Tracked | `config/valocheck/intro.json` |
| `data/2025_xmas_gacha.csv` | Master configuration | No | No known user state | Tracked | `config/events/2025-xmas/rewards.csv` |
| `data/valo_check_completed.json` | Runtime state | Yes | Yes: IDs, answers, scores | Tracked and modified | `/var/lib/wankorobot/valocheck/completed.json` initially; SQLite later |
| `data/2026_omikujii_points.json` | Runtime state | Yes, every minute | Yes: IDs and points | Tracked and modified | `/var/lib/wankorobot/events/2026-omikuji/points.json` initially |
| `data/2026_joya_state.json` | Runtime state | Yes | Yes: IDs/state | Tracked | `/var/lib/wankorobot/events/2026-joya/state.json` initially |
| `data/xmas_gacha_state.json` | Runtime state | Yes | Potentially: IDs/nicknames | Tracked | `/var/lib/wankorobot/events/2025-xmas/state.json` initially |
| `valomap_bans.json` | Runtime state | Yes | No known personal data | Ignored | `/var/lib/wankorobot/valomap/bans.json` |
| `bot.log`, `bot.err` | Log | Yes | May include IDs/names/errors | Ignored | journald or `/var/log/wankorobot/` with rotation |
| `cogs/__pycache__/` | Generated cache | Yes | No | Ignored | Not deployed/copied |
| `OLD/` | Historical source | No | Unknown until separately audited | Tracked | `archive/legacy/` or Git history |

Adding tracked runtime paths to `.gitignore` does not remove them from Git. A
later migration must preserve and back up the live files, change application
paths, validate the copied data, and only then remove the old paths from the Git
index. That migration is intentionally outside this change.

## Persistence requirements

Future runtime storage must provide:

1. A single deployment-owned root path, configurable without code changes.
2. Atomic writes or database transactions.
3. Schema versions and explicit validation.
4. Protection from two Bot processes writing the same state.
5. Backup and tested restore procedures.
6. Restrictive permissions for user-related data.
7. Retention/deletion rules for diagnostic answers and other personal data.
8. No dependency on the Git working tree.

For the current single-VPS design, SQLite is the preferred long-term runtime
store. Master configuration should remain human-reviewable JSON/CSV in Git.

## Current JSON access boundary

JSON file access is centralized in `storage/json_store.py`. Both runtime state
and master configuration use explicit UTF-8 reads. Runtime writes serialize to
a uniquely named temporary file in the destination directory, flush and sync
the file, and then atomically replace the destination. A failed serialization
or replace leaves the previous destination intact and removes the temporary
file.

A missing runtime file still produces the same Cog-specific default structure.
Malformed JSON is logged by path without logging its contents and raises an
error instead of being treated as empty state. This prevents a later save from
silently replacing damaged, potentially recoverable data.

Atomic replacement prevents partial JSON files and collisions on a shared
fixed `.tmp` filename. It does not provide transactions across multiple files,
merge concurrent read-modify-write operations, or coordinate multiple Bot
processes. Those concerns remain migration requirements for a future SQLite
storage implementation.
