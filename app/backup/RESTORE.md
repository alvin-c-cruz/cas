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
- The CAS code at the same (or newer, migration-compatible) revision — held by the **developer**
  in the private repo, deployed only to **dev-controlled** infrastructure, never delivered to the client.

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

## Scenario 2 — the host is down: the DEVELOPER redeploys to a dev-controlled host

> **Codebase-protection invariant.** The client owns their **data** (the encrypted
> `.db.enc` in *their* Drive); the developer owns the **code** (private repo) + the AES key.
> Recovery is performed **by the developer, onto infrastructure the developer controls** —
> a pre-provisioned warm standby or a fresh host. CAS ships as raw `.py`, so a runnable copy
> **is** literal source: the code is **never** placed on, or run from, a client machine.
> `backup-restore --from-storage` needs only the key + the client's Drive artifact, so it
> restores the DATA without ever handing over the engine.

On the **dev-controlled** standby / replacement host (has the private repo + venv + Drive access):

```bash
# 1. Bring up the code on infra WE control (standby already provisioned, or fresh clone):
git clone <private-repo> cas && cd cas          # private repo — never delivered to the client
python -m venv venv && venv/bin/pip install -r requirements.txt
# 2. Pull the client's newest backup from THEIR Drive and restore it (key + .env set):
python -m flask backup-restore --into instance/_restored.db --from-storage
sqlite3 instance/_restored.db "PRAGMA integrity_check"   # -> ok
mv instance/_restored.db instance/ric.db                 # .env: sqlite:///ric.db
python -m flask db upgrade                                # schema to head
# 3. Reload the app on the new host, then cut the client's CUSTOM DOMAIN (low-TTL CNAME)
#    over to it. (A *.pythonanywhere.com subdomain can't be repointed — hence the custom domain.)
```

**Data-only fallback (developer, key + one `.db.enc`, no app/DB):** decrypting an artifact yields a
**code-free** SQLite file — this is the client's data and *may* be handed to the client; the CAS
application is not. Use it to hand off data, or to seed a restore on a dev-controlled host:

```bash
python -c "from app.backup.crypto import decrypt, FileKeyProvider as K; \
open('ric.db','wb').write(decrypt(open('cas-XXXX.db.enc','rb').read(), K('<key>')))"
```

**In both scenarios the two non-negotiables are:** you have the AES key, and you `integrity_check`
(and ideally `/audit`-tie-out) the restored DB before trusting it. Never overwrite a hot DB file.
**A third, for Scenario 2:** the code runs only on dev-controlled infrastructure — never at the client.

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
- **DB restore round-trip: ~1.8s** (664 KB-class DB; verify + restore each ~1–2s). This is the
  decrypt+restore step ONLY — **not** the disaster RTO. Real recovery time is dominated by standing
  up the host and DNS cutover: **~5–15 min** with a pre-provisioned warm standby, **~30–90 min** for
  a cold rebuild. Scenario-2 full failover (host provision + `--from-storage` + domain cutover) is
  **not yet rehearsed** — add a game-day row here once a warm standby exists.
- Deep `/audit` tie-out: to be run as the interactive manual step per procedure #4 before
  a production go-live cutover.
