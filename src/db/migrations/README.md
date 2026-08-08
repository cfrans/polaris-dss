# Database migrations

Each file is applied exactly once, inside a transaction, and recorded in `schema_migrations` with
its SHA-256 checksum.

```bash
python -m src.db.migrate            # apply pending migrations
python -m src.db.migrate --status   # show the state of each migration
python -m src.db.migrate --dry-run  # preview without applying
```

## Rules

1. **Never edit a migration that has already been applied.** The runner compares checksums and
   aborts if a file changed after being applied. To adjust something, add a new migration.
2. **File name:** `NNN_short_description.sql` — three digits, lowercase, underscores.
   Numbers are sequential and never reused.
3. **Forward-only.** There are no `down` migrations: this project reaches a point where the audit
   table holds the primary research data, and an automated rollback that drops it is a footgun, not
   a feature. To undo a change, write a new migration that undoes it.
4. **One concern per migration.** Adding a column and rewriting a view belong in separate files.
5. Write `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` and `CREATE OR REPLACE VIEW` so a partially
   applied migration can be retried safely.

## Why not just re-run a schema file

`CREATE TABLE IF NOT EXISTS` creates the table when it is absent, but does **not** alter an existing
one. Re-running a schema file against a live database succeeds and changes nothing, which looks like
success. On top of that, PostgreSQL's `docker-entrypoint-initdb.d` only runs on first volume
creation, so `docker compose up -d` skips it entirely on an existing database.
