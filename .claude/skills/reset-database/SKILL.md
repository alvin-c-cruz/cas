---
name: reset-database
description: Use when the user types /reset-database or asks to reset, wipe, or reinitialise the CAS database from scratch.
---

# /reset-database — Full CAS Database Reset

Two-phase flow: **seed analysis first** (read-only, safe), then **destructive reset** (only after approval).

---

## Phase 1 — Seed Analysis (read-only)

**Goal:** Ensure `seed_data.py::seed_minimal()` is current before anything is deleted.

### Step 1.1 — Read models and seed data in parallel

Use the Read tool on all of these simultaneously:

- `C:\envs\cas\CLAUDE.md`
- `C:\envs\cas\app\users\models.py`
- `C:\envs\cas\app\branches\models.py`
- `C:\envs\cas\app\settings.py`
- `C:\envs\cas\app\vat_categories\models.py`
- `C:\envs\cas\app\withholding_tax\models.py`
- `C:\envs\cas\app\seeds\seed_data.py`

### Step 1.2 — Compare each entity

Check `seed_minimal()` against each model:

| Entity | Model | What to check |
|--------|-------|---------------|
| SuperUser | `User` | username, role, is_active, branch assignment |
| Main Branch | `Branch` | code, name, address, is_active |
| App Settings | `AppSettings` | all keys present, no stale keys |
| VAT Categories | `VATCategory` | codes match BIR usage in views/forms |
| WHT Codes | `WithholdingTax` | codes and rates match usage in forms/views |

Look for:
- Required model fields missing from the seed
- Fields seeded that no longer exist on the model
- VAT/WHT codes referenced in the codebase but absent from seed, or vice versa

Judgment rules:
- **Always propose additions** — if the codebase references a key/code the seed doesn't include, add it.
- **Flag deletions for user review** — if the seed includes something no longer in the models, surface it but let the user decide whether to remove it.

### Step 1.3 — Present findings and wait for approval

Present a diff-style report:

```
SEED ANALYSIS REPORT
====================

SuperUser         ✓ No changes needed
Main Branch       ✓ No changes needed
App Settings      ! Missing key: invoice_prefix (used in sales_invoices/views.py:45)
VAT Categories    ✓ No changes needed
WHT Codes         ✓ No changes needed

Proposed change to seed_data.py::seed_minimal():
  + {'key': 'invoice_prefix', 'value': 'SI'}
```

**STOP HERE.** Do not proceed to Phase 2 until the user approves or declines the proposed changes.

- If changes approved → patch `seed_data.py`, commit, push, then proceed to Phase 2.
- If no changes needed → confirm "Seed data is current." and proceed to Phase 2.
- If user declines changes → note that seed will not be updated and proceed to Phase 2.

Patching `seed_data.py` requires explicit approval per CLAUDE.md ("Propose before seeding/bulk-writing").

---

## Phase 2 — Destructive Reset

Only runs after Phase 1 is complete and user has responded.

### Step 2.1 — Kill server

```powershell
$pids = (netstat -ano | Select-String ":5000 " | Select-String "LISTENING" | ForEach-Object { ($_ -split '\s+')[-1] } | Sort-Object -Unique)
if ($pids) {
    $pids | ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }
    Write-Host "Killed PIDs: $($pids -join ', ')"
} else {
    Write-Host "No server running on port 5000"
}
```

### Step 2.2 — Verify port 5000 is free

```powershell
$still = netstat -ano | Select-String ":5000 " | Select-String "LISTENING"
if ($still) {
    Write-Host "ERROR: Port 5000 still in use. Cannot proceed."
    $still
} else {
    Write-Host "Port 5000 is free. Proceeding."
}
```

**If port 5000 is still in use: STOP and report the output. Do not delete the database.**

Before stopping, run the fallback below. netstat's PID column can lie: a listening PID may already be **dead** while a *different* live process inherited the listening socket. In that case Step 2.1 (which kills only the netstat-listed PIDs) frees nothing and retrying the same PID list is futile. Enumerate the live interpreters that may actually hold the port:

```powershell
$pyprocs = Get-Process python, flask -ErrorAction SilentlyContinue
if ($pyprocs) {
    Write-Host "Live python/flask processes that may hold :5000 (CONFIRM before killing — could be other sessions):"
    $pyprocs | Format-Table Id, ProcessName, StartTime -AutoSize
} else {
    Write-Host "No live python/flask processes found."
}
```

These live processes may belong to **another Claude session's dev server** (see `feedback-multi-session-awareness`). Do NOT kill them silently — present the list and get explicit user approval first. Only after approval, kill the approved PIDs, then re-run Step 2.2. The "port still in use → STOP" gate remains in force: if the port is still LISTENING after the approved kills, STOP and report — do not delete the database.

### Step 2.3 — Delete the database

```powershell
Remove-Item -Force "C:\envs\cas\instance\cas.db"
```

Note: No `-ErrorAction SilentlyContinue`. If this errors, surface the error and stop.

### Step 2.4 — Verify the file is gone

```powershell
if (Test-Path "C:\envs\cas\instance\cas.db") {
    Write-Host "ERROR: instance/cas.db still exists. File lock was not released."
} else {
    Write-Host "instance/cas.db deleted successfully."
}
```

**If the file still exists: STOP and report. The process did not release the file lock.**

### Step 2.5 — Recreate schema

```powershell
cd C:\envs\cas; flask db upgrade
```

If this exits with a traceback, stop and report the full error.

Note: On a fresh DB, Alembic prints only "Context impl SQLiteImpl / Will assume non-transactional DDL" with no individual migration steps listed — this is normal and expected. Do not treat missing migration step output as an error.

### Step 2.6 — Seed baseline data

```powershell
cd C:\envs\cas; flask seed-minimal
```

Always use `flask seed-minimal`, not `flask seed-db`. The minimal seeder:
- Assigns the admin user to Main Branch
- Uses correct BIR VAT codes (VEX, V0, INV, V12CG, V12DG, V12SV, V12IM)
- Seeds 19 app settings including company officers, RDO code, print access, company_logo, and environment

### Step 2.7 — Report

Tell the user:

```
RESET COMPLETE
==============
Server:     Killed PIDs [x, y] / No server was running
DB:         instance/cas.db deleted and recreated
Seed:       flask seed-minimal — admin user, main branch, 19 app settings, 28 COA accounts, 7 VAT codes, 3 WHT codes
Seed diff:  [summary of any seed_data.py changes from Phase 1, or "none"]
Uploads:    instance/uploads/ is NOT cleared by reset; company_logo is reset to '' so any
            previously-uploaded logo is now orphaned on disk. Re-upload via Company Settings,
            or re-link the fresh DB to the surviving file.

Login:      admin / admin123
```

---

## Hard Rules

- Phase 2 never starts before Phase 1 is complete and the user has responded.
- Never use `-ErrorAction SilentlyContinue` on the DB delete step.
- Never edit `seed_data.py` without explicit user approval.
- Use `flask seed-minimal`, not `flask seed-db`.
- If port 5000 is still in use after killing, stop — do not delete the DB.
- If `instance/cas.db` still exists after `Remove-Item`, stop — do not run migrations.
