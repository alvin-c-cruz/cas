# CAS project self-test — UI specs

Durable, harness-driven browser specs for **`/ui-test cas`** (the CAS base project's
**empty-schema self-test**: schema migrated to head, **zero rows**, no client backup).

These are the versioned regression guards for **browser-only** CAS behavior — the class the
pytest suite + `/guard` can't catch (real DOM, multi-role flows, first-run/empty-state). One file =
one case. Run them with the CAS venv during a `/ui-test cas` session:

```
C:/envs/erp-workspace/projects/cas/venv/Scripts/python.exe clients/cas/ui-tests/<file>.py
```

## How an empty-CAS session bootstraps (no seeding)

An empty DB has no users, so you build all state through the UI, starting with the first-run admin:

1. Register the **exact username `admin`** at `/register` — the first-run bootstrap
   (`system_has_admin()` in `app/users/utils.py`) bypasses the ApprovedEmail whitelist, creates
   that user `role='admin', is_active=True`, and auto-creates a default `MAIN` branch assigned to
   them, so they land on a working dashboard. The bypass closes the instant an admin exists.
2. As `admin`, build the rest via the UI: chart of accounts, VAT/WHT, additional branches, and —
   per discipline #4 — pre-approve accountant/staff emails so they self-register (admin as a last
   resort). Then drive the feature under test.

> Requires the running CAS code to include the first-run bootstrap (CAS `main` ≥ 2026-07-11,
> `project-bug-tracker` BUG-NO-FIRSTRUN-ADMIN-BOOTSTRAP). If the shared working tree is checked out
> on a branch without it, the empty-DB bootstrap won't work yet.

## Conventions (see `.claude/skills/ui-test/SKILL.md`)

- Add `.claude/skills/ui-test/` to `sys.path`, `import harness`, `harness.connect(pw)`.
- **Discipline #6:** when a bug logged via `/ui-test` is fixed, add a spec here that reproduces the
  original failure and asserts the fix. The Step 8 regression pass runs every spec here on each
  provision and re-opens any fixed bug that regressed.
- First spec to add (owner-directed): a **first-run bootstrap** guard — empty DB → register `admin`
  → assert active admin + `MAIN` branch + working dashboard, and that the bypass is closed once an
  admin exists (BUG-NO-FIRSTRUN-ADMIN-BOOTSTRAP). Verify green on a fix-bearing `/ui-test cas` env
  before committing.
