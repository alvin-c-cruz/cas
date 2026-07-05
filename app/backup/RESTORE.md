# CAS Backup — Restore Runbook

> These snapshots are a **disaster-recovery / archival copy — NOT the BIR-registered
> books of account.** CAS is not a BIR-accredited Computerized Accounting System.

## What a backup contains

One AES-256-GCM–encrypted snapshot of the instance database (`VACUUM INTO` copy,
integrity-checked before upload) named `cas-<PH-timestamp>.db.enc`, plus a plaintext
JSON manifest (hashes/sizes only). Stored on-server via `LocalStorage`
(`BACKUP_LOCAL_DIR`) and/or off-site in Google Drive (`BACKUP_STORAGE=gdrive`). Retention
keeps the newest `BACKUP_RETENTION_COUNT` (default 30) backups; older ones are pruned.
Uploads/attachments are not yet in the backup (separate slice).

## Prerequisites to restore

- The **encryption key file** (`BACKUP_ENC_KEY`, base64 of 32 bytes). **Without it the
  backup is unrecoverable ciphertext.** A copy must live in the password manager, separate
  from the server.
- The CAS code at the same (or newer, migration-compatible) revision.

## Restore commands

Run from the app root (`projects/cas/`) with the instance's env (`.env` + `BACKUP_*`).
**Never restore over the live DB** — `backup-restore` refuses if `--into` equals the live path.

- `flask backup-verify` — latest backup is decryptable + intact (non-destructive).
- `flask backup-restore --into <scratch>` — restore the latest good backup. Finds it via the
  `BackupRun` table, so it needs a **working app DB** (use it to roll back to an older copy).
  `--run-id N` picks a specific run.
- **`flask backup-restore --into <scratch> --from-storage`** — DISASTER RECOVERY. Finds the newest
  artifact by **listing Drive/local directly**, so it works even when **`ric.db` is gone/corrupt**
  (the `BackupRun` table lives inside `ric.db`, so the default lookup can't help then).

## Scenario 1 — PA is up, but `ric.db` is deleted/corrupted

On PA (Bash console), from `~/cas`, with the venv active:

```bash
python -m flask backup-restore --into ~/restored.db --from-storage
sqlite3 ~/restored.db "PRAGMA integrity_check"       # -> ok
# (ideally boot a scratch server on it and run /audit: 3-way tie-out + trial-balance = 0)
# cut over: stop the web app, then:
mv ~/restored.db ~/cas/instance/ric.db               # never copy onto a hot/running DB
# Reload the web app (Web tab or: touch /var/www/<user>_pythonanywhere_com_wsgi.py)
```

## Scenario 2 — PA is down; run CAS on localhost while finding a new host

On your local machine (has the repo + venv + the encrypted backups / Drive access):

```bash
cd projects/cas
# get the newest cas-*.db.enc (from Drive RIC-CAS-Backups, or already local), then either
# use the CLI (BACKUP_STORAGE + BACKUP_ENC_KEY set in .env):
python -m flask backup-restore --into instance/_restored.db --from-storage
# ...or decrypt a specific .db.enc directly (no app/DB needed — only the key):
python -c "from app.backup.crypto import decrypt, FileKeyProvider as K; \
open('instance/_restored.db','wb').write(decrypt(open('cas-XXXX.db.enc','rb').read(), K('<key>')))"

sqlite3 instance/_restored.db "PRAGMA integrity_check"   # -> ok
mv instance/_restored.db instance/ric.db
# .env: SQLALCHEMY_DATABASE_URI=sqlite:///ric.db
python -m flask db upgrade                               # schema to head
python flask_app.py                                     # CAS live at http://localhost:5050
# When a new cloud host is ready: deploy CAS there and upload this ric.db.
```

**In both scenarios the two non-negotiables are:** you have the AES key, and you `integrity_check`
(and ideally `/audit`-tie-out) the restored DB before trusting it. Never overwrite a hot DB file.

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
