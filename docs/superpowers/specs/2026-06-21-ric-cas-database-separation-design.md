# RIC / CAS Database Separation — Design

**Date:** 2026-06-21
**Status:** Approved (Approach 1)

## Context

CAS is a single, industry-agnostic accounting product. "RIC" is not a separate
codebase — it is a specific client's data being migrated *into* CAS (GL replay,
COA rebuild, MONDE customer, SI 0029235, etc.). To date that real client data and
some legacy-import test data have accumulated in the single dev database
`instance/cas.db`.

The two will now be **deployed on separate servers for client presentation**:

- **RIC server** — the real migrated client data.
- **CAS server** — a clean, generic demo instance (built *later*).

The application's database target is already fully env-driven
(`SQLALCHEMY_DATABASE_URI` in `.env`, with `.env` documented as the single source
of truth). Pointing a deployment at a different database therefore needs **no
application code changes**.

## Decision

**Approach 1 — env-per-deployment with explicit DB filenames.** Same codebase on
both servers; each server has its own `.env` (own DB URI), its own
`instance/uploads` (logo files), and its own `company_name` setting (stored in the
DB). Locally we make the current database the RIC database by giving it an
honest filename.

Rejected alternatives:
- *`CAS_INSTANCE=ric|cas` profile var in `config.py`* — adds an abstraction for
  only two instances when `.env` already selects the DB and branding already lives
  in the DB. YAGNI.
- *Pure documentation, no rename* — leaves `cas.db` misleadingly holding RIC data
  and leaves the `/reset-database` foot-gun in place.

## Scope (this change)

1. **Rename the local DB to state the truth.**
   - Copy `instance/cas.db` → `instance/ric.db` (new canonical RIC DB).
   - Keep the old file as a backup: rename `instance/cas.db` →
     `instance/cas.db.bak-pre-ricrename` (gitignored).
   - Update local `.env`: `SQLALCHEMY_DATABASE_URI=sqlite:///ric.db`.

2. **`.gitignore`** — add `ric.db` (and `*.db.bak-*`) so the new DB and backups are
   never committed (DBs are local/per-server data).

3. **`.env.example`** — document the per-instance pattern: each deployment sets its
   own `SQLALCHEMY_DATABASE_URI` (e.g. `sqlite:///ric.db` for the RIC server,
   `sqlite:///cas_demo.db` for the CAS demo server).

4. **`/reset-database` skill — make it DB-name-aware (safety-critical).**
   - Resolve the target DB path from `SQLALCHEMY_DATABASE_URI` in `.env` instead of
     hardcoding `instance/cas.db`.
   - Before deleting, print the resolved target filename and require explicit,
     name-matching confirmation. This prevents `seed-minimal` from silently wiping
     RIC's real migration data.

5. **Deployment doc** — short note (CLAUDE.md "Deployment" section + this spec) on
   the two-server model: same repo, per-server `.env`, per-server
   `instance/uploads`, per-server DB file.

## Deployment model (two servers)

| Concern            | RIC server                       | CAS server (later)                 |
|--------------------|----------------------------------|------------------------------------|
| Code               | same repo                        | same repo                          |
| `.env` DB URI      | `sqlite:///ric.db`               | `sqlite:///cas_demo.db`            |
| Data               | migrated real client data        | `flask seed-db` fresh demo         |
| `company_name`     | RIC's registered name (DB setting)| demo name (DB setting)            |
| Logo               | RIC logo in its `instance/uploads`| demo logo in its `instance/uploads`|

## Caveats

- **Logo is a file, not a DB row.** `company_logo` stores a *filename*; the image
  lives in `instance/uploads`. It does **not** travel inside the `.db`. Each server
  keeps its own uploads directory — fine for separate servers; only matters if both
  DBs are ever run on one machine (then uploads would collide).
- **Shared schema/migrations.** Both DBs share one migration history (same code).
  `flask db upgrade` is run against whichever DB `.env` points at.
- **Renaming requires the server stopped** (SQLite file lock). Verified stopped at
  design time.

## Out of scope (deferred)

- Building/seeding the actual CAS demo database (done later, on its own server).
- Any `CAS_INSTANCE` profile abstraction.
- Postgres / non-SQLite backends.

## Rollback

The pre-rename database is preserved as `instance/cas.db.bak-pre-ricrename`. To
revert: stop the server, copy the backup back to `instance/cas.db`, and restore
`.env` to `SQLALCHEMY_DATABASE_URI=sqlite:///cas.db`.
