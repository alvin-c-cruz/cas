# CAS Backup — Restore Runbook

> These snapshots are a **disaster-recovery / archival copy — NOT the BIR-registered
> books of account.** CAS is not a BIR-accredited Computerized Accounting System.

## What a backup contains

One AES-256-GCM–encrypted snapshot of the instance database (`VACUUM INTO` copy,
integrity-checked before upload) plus a plaintext JSON manifest (hashes/sizes only).
Slice 1 stores these on-server via `LocalStorage` (`BACKUP_LOCAL_DIR`). Uploads/attachments
and off-site (Google Drive) are later slices.

## Prerequisites to restore

- The **encryption key file** (`BACKUP_ENC_KEY`, base64 of 32 bytes). **Without it the
  backup is unrecoverable ciphertext.** A copy must live in the password manager, separate
  from the server.
- The CAS code at the same (or newer, migration-compatible) revision.

## Restore procedure

Run from the app root (`projects/cas/`) with the instance's env (`.env` +
`BACKUP_*`). **Never restore over the live DB** — the CLI refuses if `--into` equals
the live database path.

```bash
# 1. Verify the latest backup is decryptable + intact (cheap, non-destructive)
python -m flask backup-verify
#    -> verify ok=True {'integrity': True, 'sha256_match': True}

# 2. Restore the latest good backup into a SCRATCH file
python -m flask backup-restore --into instance/_restored.db
#    (add --run-id N to restore a specific run)

# 3. Confirm the restored file is intact
python -c "import sqlite3; print(sqlite3.connect('instance/_restored.db').execute('PRAGMA integrity_check').fetchone()[0])"
#    -> ok

# 4. DEEP proof (do this before trusting a restore for go-live):
#    point a scratch server at the restored DB and run the /audit workspace skill,
#    confirming the three-way tie-out AND trial-balance = 0. /audit is interactive
#    (no headless callable yet — that automation is a deferred slice).

# 5. To cut over: stop the web app, move the restored file into place as the live DB,
#    restart. Do NOT copy over a hot/running DB file.
```

## Key custody

- Live key: `BACKUP_ENC_KEY` path, **outside** the web root and outside `instance/uploads/`.
- Backup copy: the owner's password manager (off-server). Loss of the key = permanent loss.
- Rotation: `key_id` is recorded per artifact/manifest; retired keys must be kept read-only
  so old backups stay decryptable.

## Rehearsal record

| Date | Source | Result |
|---|---|---|
| 2026-07-05 | copy of `cas.db` (demo: 79 accounts, 1220 journal_entries, 2 users) | ✅ backup→verify→restore round-trip PASSED |

- `backup-verify`: `ok=True` (integrity + plaintext-sha256 match).
- `backup-restore` → scratch: restored file `integrity_check = ok`.
- Data fidelity vs source: accounts 79=79, journal_entries 1220=1220, users 2=2 (exact).
- **RTO: ~1.8s** (664 KB-class DB; verify + restore each ~1–2s).
- Deep `/audit` tie-out: to be run as the interactive manual step per procedure #4 before
  a production go-live cutover.
