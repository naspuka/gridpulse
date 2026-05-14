# Migrations

Plain SQL, applied in numeric order by `gridpulse.storage.migrate`.

## Conventions

- File names: `NNN_short_description.sql` (e.g. `004_raw_carbon_intensity.sql`).
- Numbering increments by 1; never reuse a number.
- Each file runs inside one transaction. Keep multiple related DDL statements
  in a single file when they must commit atomically.
- **TimescaleDB note:** `create_hypertable(...)` and `add_retention_policy(...)`
  do run inside transactions in TimescaleDB ≥ 2.x. No special handling needed.

## Applying

```bash
# From a venv against localhost Postgres
uv run python -m gridpulse.storage.migrate

# Or via Make
make migrate
```

The migrator is idempotent — re-running does nothing if all versions are
already in `public._migrations`.

## Authoring a new migration

1. Bump the number (e.g. next is `002_*.sql` after the bootstrap).
2. Write the DDL.
3. `make migrate` locally to apply it.
4. Add a corresponding rollback note in this README if the migration is
   non-trivial (e.g. data backfills, column renames).

There is **no down-migration** mechanism. Rolling back means writing a new
forward migration that undoes the previous one. This is intentional —
real prod migrations are usually forward-only.
