---
name: guard
description: Use when the user types /guard or asks to check for regressions before pushing. Maps changed files to the "done" modules that depend on them (via .claude/regression-map.json), runs those modules' tests + e2e smoke, and reports newly-broken vs. the known baseline.
---

# /guard — Pre-Push Regression Check

Catches the failure mode where editing a high-blast-radius shared file (e.g.
`app/static/search-select.js`, `transaction-utils.js`, `app/vendors/utils.py`) for one
module silently breaks a "finished" module that reuses it. Pairs with `/retro` (which is
reflective/after-the-fact); `/guard` is preventive/before-the-push.

## Steps

**1. Find affected modules.** Run the mapping helper:

```powershell
python .claude/guard.py
```

It diffs the branch against `main` (+ uncommitted changes), consults
`.claude/regression-map.json`, and prints the affected modules and the suggested pytest
commands. If it says "nothing to guard," no blast-radius file changed — stop, report that.

**2. Run the e2e smoke gate** (the JS-layer net — this is what pytest's HTML tests miss).
Ensure the chromium browser is installed once (`python -m playwright install chromium`), then:

```powershell
python .claude/guard.py --run-e2e
```

Exit code 0 = smoke passed; non-zero = a real browser-layer regression (it prints which).

**3. Run the affected modules' full suite** (unit + integration) using the marker the helper
suggested, e.g.:

```powershell
python -m pytest -m "accounts_payable or cash_disbursements" -o addopts="-m 'accounts_payable or cash_disbursements'" -q
```

(Use `-o addopts=...` to override the default `-m "not e2e"` so the run isn't filtered; or
just run `python -m pytest -m "<markers>"` — the command-line `-m` overrides the config.)

**4. Compare to the baseline.** Read
`C:\Users\user\.claude\projects\C--envs-cas\memory\project-preexisting-test-failures.md`.
Report ONLY tests that are **newly** broken vs. that baseline — known-baseline failures are
not a guard finding. Call out e2e failures prominently: those are always real (the e2e suite
is kept green).

**5. Report.** Summarize: affected modules, e2e gate result, newly-broken tests (or "none"),
and a clear verdict — safe to push or not. If something broke, name the shared file that most
likely caused it (from the map) so the fix is targeted.

## Notes
- The pre-push git hook (`.claude/githooks/pre-push`) runs step 2 automatically and blocks a
  push on e2e failure. `/guard` is the manual, fuller version (adds steps 3-4).
- When you add a new shared file or a new module e2e suite, update `.claude/regression-map.json`
  (set the module's `e2e` path) in the same change — a stale map is a silent coverage hole.
- Escape hatch for the hook: `GUARD_SKIP=1 git push` (use sparingly).
