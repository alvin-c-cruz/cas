# /reset-database Skill Design

**Date:** 2026-06-14  
**Skill command:** `/reset-database`  
**Skill file:** `~/.claude/skills/reset-database.md`

---

## Purpose

Reset the CAS development database to a clean, fully-seeded baseline. Used when:
- The DB is corrupted or in an inconsistent state
- Starting a fresh demo or test run
- Seed data has drifted from the current codebase

---

## Root Cause Addressed

Previous reset attempts silently failed because `Remove-Item -ErrorAction SilentlyContinue` hid a Windows file-lock error — the Flask server held `instance/cas.db` open, the delete appeared to succeed but the file remained, and every subsequent command ran against the original populated database. The skill must kill the server and verify the port is free **before** touching the database file.

---

## Two-Phase Flow

### Phase 1 — Seed Analysis (read-only, no destructive actions)

**Goal:** Ensure `seed_data.py::seed_minimal()` is current before the reset runs.

**Steps:**

1. Read in parallel:
   - `CLAUDE.md` — project context and domain rules
   - `app/users/models.py` — User fields
   - `app/branches/models.py` — Branch fields
   - `app/settings.py` — AppSettings keys
   - `app/vat_categories/models.py` — VATCategory fields and code constants
   - `app/withholding_tax/models.py` — WithholdingTax fields and rate patterns
   - `app/seeds/seed_data.py` — current `seed_minimal()` content

2. Compare each seed entity against its model:
   - Are all required fields present in the seed?
   - Are any fields seeded that no longer exist on the model?
   - Are VAT codes and WHT codes consistent with how they're referenced in views and forms?

3. Check all five seed entities:
   | Entity | Model | Seed function check |
   |--------|-------|-------------------|
   | SuperUser | `User` | username, role, is_active, branch assignment |
   | Main Branch | `Branch` | code, name, address, is_active |
   | App Settings | `AppSettings` | all keys present, no stale keys |
   | VAT Categories | `VATCategory` | codes match BIR usage in codebase |
   | WHT Codes | `WithholdingTax` | codes and rates match usage in forms/views |

4. Present a clear diff report of proposed changes to `seed_data.py`.

5. **Wait for user approval.** Do not proceed to Phase 2 until approved.

6. If changes approved: patch `seed_data.py`, commit, and push.

7. If no changes needed: note that and proceed to Phase 2.

---

### Phase 2 — Reset (destructive, runs after Phase 1 approval)

**Steps:**

1. Kill all processes on port 5000:
   ```powershell
   $pids = (netstat -ano | Select-String ":5000 " | Select-String "LISTENING" | ForEach-Object { ($_ -split '\s+')[-1] } | Sort-Object -Unique)
   if ($pids) {
       $pids | ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }
   }
   ```

2. **Verify** port 5000 is free. If any PID still holds port 5000, **stop and report** — do not continue.

3. Delete `instance/cas.db`:
   ```powershell
   Remove-Item -Force "C:\envs\cas\instance\cas.db"
   ```
   Note: Do NOT use `-ErrorAction SilentlyContinue` — any error here must be surfaced.

4. **Verify** `instance/cas.db` no longer exists. If the file is still present, **stop and report** — the process did not release the file lock.

5. Run migrations:
   ```powershell
   flask db upgrade
   ```

6. Seed baseline data:
   ```powershell
   flask seed-minimal
   ```

7. Report to user:
   - PIDs killed (or "no server was running")
   - Confirmation that DB file was deleted
   - Any `seed_data.py` changes made in Phase 1
   - Full output of `flask seed-minimal`
   - Login credentials: username `admin` / password `admin123`

---

## Seed Baseline (`flask seed-minimal`)

| # | Entity | Detail |
|---|--------|--------|
| 1 | SuperUser | username `admin`, role `admin`, assigned to Main Branch |
| 2 | Main Branch | code `MAIN`, name `Main Branch` |
| 3 | App Settings | 14 keys: company name, TIN, address, fiscal year, RDO, officers, etc. |
| 4 | Chart of Accounts | 22 accounts (hierarchical: Cash, Input VAT, AP, WHT Payable, Operating Expenses) |
| 5 | VAT Categories | 7 BIR codes: VEX, V0, INV, V12CG, V12DG, V12SV, V12IM |
| 6 | WHT Codes | WC158 (1%), WC160 (2%), WC100 (5%) |
| 7 | Vendors | 9 demo vendors with VAT/WHT defaults |

---

## Hard Rules

- Phase 2 never runs before Phase 1 is reviewed and approved.
- Never use `-ErrorAction SilentlyContinue` on the DB delete — silent failure is the root cause of the original bug.
- Never edit `seed_data.py` without user approval (per CLAUDE.md: "Propose before seeding/bulk-writing").
- Use `flask seed-minimal`, not `flask seed-db` — minimal has richer app settings, correct BIR VAT codes, and assigns admin to branch automatically.
- The root-level `cas.db` (0 bytes, stale) can be ignored — the app reads from `instance/cas.db`.
