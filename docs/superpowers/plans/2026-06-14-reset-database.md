# /reset-database Skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rewrite `~/.claude/skills/reset-database.md` to implement the approved two-phase design: seed analysis + approval first, then hard-verified destructive reset.

**Architecture:** Single skill file. Phase 1 reads all five entity models against `seed_data.py::seed_minimal()` and presents a diff for approval. Phase 2 kills the server, verifies the port is free, deletes the DB (without `-ErrorAction SilentlyContinue`), verifies the file is gone, then runs migrations and seeds.

**Tech Stack:** PowerShell (Windows), Flask CLI, SQLite, Claude skill markdown format.

---

## File Map

| Action | Path |
|--------|------|
| Rewrite | `C:\Users\user\.claude\skills\reset-database.md` |

---

### Task 1: Rewrite the skill file

The current draft has three critical bugs fixed by the approved design:
1. Phase order reversed — analysis must come before kill/delete
2. `-ErrorAction SilentlyContinue` on the DB delete hides the file-lock error (the diagnosed root cause)
3. No hard verification after kill or after delete — process can still hold the file

**Files:**
- Rewrite: `C:\Users\user\.claude\skills\reset-database.md`

- [ ] **Step 1: Overwrite the skill file with the approved two-phase design**

Replace the entire contents of `C:\Users\user\.claude\skills\reset-database.md` with:

```markdown
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

Note: On a fresh DB, Alembic prints only "Context impl SQLiteImpl / Will assume non-transactional DDL" with no migration steps listed. This is normal.

### Step 2.6 — Seed baseline data

```powershell
cd C:\envs\cas; flask seed-minimal
```

Always use `flask seed-minimal`, not `flask seed-db`. The minimal seeder:
- Assigns the admin user to Main Branch
- Uses correct BIR VAT codes (VEX, V0, INV, V12CG, V12DG, V12SV, V12IM)
- Seeds 14 app settings including company officers and RDO code

### Step 2.7 — Report

Tell the user:

```
RESET COMPLETE
==============
Server:     Killed PIDs [x, y] / No server was running
DB:         instance/cas.db deleted and recreated
Seed:       flask seed-minimal — all 7 categories seeded fresh
Seed diff:  [summary of any seed_data.py changes from Phase 1, or "none"]

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
```

- [ ] **Step 2: Verify the file was written correctly**

Read back `C:\Users\user\.claude\skills\reset-database.md` and confirm:
- Frontmatter `name: reset-database` is present
- Phase 1 comes before Phase 2
- Step 2.3 has NO `-ErrorAction SilentlyContinue`
- Steps 2.2 and 2.4 both have explicit stop conditions

---

### Task 2: End-to-end test — Phase 1 only

Invoke the skill while the server is NOT running, so Phase 1 runs but Phase 2 would be a no-op on the server kill. Verify the analysis output is correct.

**Files:**
- Read: `C:\envs\cas\app\vat_categories\models.py`
- Read: `C:\envs\cas\app\withholding_tax\models.py`
- Read: `C:\envs\cas\app\seeds\seed_data.py`

- [ ] **Step 1: Invoke `/reset-database`**

Run the skill. Let Phase 1 complete. It should:
1. Read all 7 files in parallel
2. Present a seed analysis report covering all 5 entities
3. Pause and wait for approval before proceeding

- [ ] **Step 2: Verify Phase 1 output**

Confirm the report shows a row for each of: SuperUser, Main Branch, App Settings, VAT Categories, WHT Codes.

Confirm the skill has NOT yet killed the server or deleted the DB.

- [ ] **Step 3: Approve or decline any proposed changes**

Respond to the skill. Verify it then proceeds to Phase 2.

---

### Task 3: End-to-end test — Full reset

Verify Phase 2 actually deletes and re-seeds a fresh database.

- [ ] **Step 1: Check DB has data before reset**

```powershell
cd C:\envs\cas; python -c "
import os; os.environ.setdefault('SECRET_KEY','test')
from dotenv import load_dotenv; load_dotenv()
from app import create_app, db
app = create_app('development')
with app.app_context():
    from app.users.models import User
    from app.vat_categories.models import VATCategory
    print('Users:', User.query.count())
    print('VATCategories:', VATCategory.query.count())
"
```

Expected: non-zero counts (existing data).

- [ ] **Step 2: Run `/reset-database` end-to-end**

With no server running (or with the server running to test the kill step), invoke the skill and let both phases complete.

- [ ] **Step 3: Verify fresh seed data**

```powershell
cd C:\envs\cas; python -c "
import os; os.environ.setdefault('SECRET_KEY','test')
from dotenv import load_dotenv; load_dotenv()
from app import create_app, db
app = create_app('development')
with app.app_context():
    from app.users.models import User
    from app.branches.models import Branch
    from app.vat_categories.models import VATCategory
    from app.withholding_tax.models import WithholdingTax
    from app.settings import AppSettings
    u = User.query.filter_by(username='admin').first()
    b = Branch.query.filter_by(code='MAIN').first()
    print('Admin user:', u.username, '/ role:', u.role)
    print('Admin branches:', [br.code for br in u.branches.all()])
    print('Main Branch:', b.name)
    print('VAT categories:', VATCategory.query.count())
    print('WHT codes:', WithholdingTax.query.count())
    print('App settings:', AppSettings.query.count())
"
```

Expected output:
```
Admin user: admin / role: admin
Admin branches: ['MAIN']
Main Branch: Main Branch
VAT categories: 7
WHT codes: 3
App settings: 14
```

- [ ] **Step 4: Verify login works**

Start the server and confirm login with `admin` / `admin123` succeeds.
