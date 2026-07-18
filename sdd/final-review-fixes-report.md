# Final Whole-Branch Review — 3 Polish Fixes (R-04 Slice 1, Bank Account Master)

Branch: `feat/r04-bank-account-master` (worktree started at `22c8a9f8`)

## Fix 1 — Remove CSS class shadowing in the Bank Accounts form template

**File:** `app/bank_accounts/templates/bank_accounts/form.html`

The page-local `<style>` block re-declared `.form-row-2`, `.form-error`, and
`.form-actions` with different values than the app-wide definitions in
`app/templates/base.html`'s inline `<style>` block (lines 640-706, hardcoded
values, loads last — the exact anti-pattern this app's CLAUDE.md calls out
under "Gotchas") and `app/static/css/style.css` (lines 636-653, design-token
based). Because the local block loaded after both, it silently won the
cascade.

Global values found:
- `base.html`: `.form-row-2 { display:grid; grid-template-columns:1fr 1fr; gap:20px; }`,
  `.form-error { font-size:12px; color:#ef4444; margin-top:6px; }`,
  `.form-actions { display:flex; gap:12px; margin-top:24px; ... }`
- `style.css`: `.form-row-2 { display:grid; grid-template-columns:1fr 1fr; gap:14px; }`
  and `.form-actions` scoped variants for specific modals.

**Before:**
```css
.page-sub { color: var(--text-2); font-size: 13px; margin: 0 0 18px; }
.form-row-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 0 18px; }
.form-hint { font-size: 11px; color: var(--text-3); margin-top: 3px; display: block; }
.required { color: #dc2626; }
.form-error { color: #dc2626; font-size: 12px; margin-top: 4px; }
.form-actions {
    display: flex; gap: 12px; justify-content: flex-start;
    margin-top: 12px; padding-top: 12px; border-top: 1px solid var(--border);
}
```

**After:**
```css
.page-sub { color: var(--text-2); font-size: 13px; margin: 0 0 18px; }
.form-hint { font-size: 11px; color: var(--text-3); margin-top: 3px; display: block; }
.required { color: #dc2626; }
```

Only the 3 shadowing rules were deleted. `.page-sub`, `.form-hint`, and
`.required` are not defined globally (grepped, no hits), so they remain local
and untouched. No other local rule depended on the exact `.form-row-2` gap
value (no nested selector referenced it). The global classes themselves
(`base.html`, `style.css`) were NOT edited, per the constraint.

## Fix 2 — Reword the shared-cash-account seeder flash message

**File:** `app/company_settings/views.py`, `modules_toggle()`

**Before:**
```python
if flags:
    flash(f'{len(flags)} cash account(s) are shared across branches — '
          f'assign each to its owning branch.', 'warning')
```

**After:**
```python
if flags:
    flash(f'{len(flags)} cash account(s) are used by more than one branch — '
          f'to give each branch its own Bank Account, split them into '
          f'separate per-branch GL accounts in the Chart of Accounts, then '
          f'register each here.', 'warning')
```

Rationale: there is no UI to "assign" a shared GL account to a branch (no
`branch_id` on `BankAccountForm`, no reassign view), and `BankAccount.account_id`
is unique, so a second `BankAccount` row for the same GL account is impossible.
The new wording names the real remedy: split the GL account per branch in the
Chart of Accounts, then register each new account as its own Bank Account.

Grepped `tests/` for the old text (`assign each to its owning branch`) and for
`shared across branches` — no test anywhere asserted this exact flash string,
so no test file needed updating for this fix.

## Fix 3 — Align `quick_add()`'s JSON response to include `account_id`

**File:** `app/bank_accounts/views.py`, `quick_add()`

**Before:**
```python
return jsonify(ok=True, bank_account={
    'id': ba.id,
    'label': f'{ba.code} - {ba.name}',
})
```

**After:**
```python
return jsonify(ok=True, bank_account={
    'id': ba.id,
    'account_id': ba.account_id,
    'label': f'{ba.code} - {ba.name}',
})
```

Kept `'id'` alongside the new `'account_id'` (low-risk, more informative) —
`cash_bank_account_choices()` elsewhere in this module already uses the GL
`account_id` as the picker's option value, so whoever wires `quick_add` into a
CRV/CDV-style picker next needs `account_id`, not `BankAccount.id`.

Grepped `tests/` for `bank-accounts/quick-add` and for any `bank_account`/`label`
JSON-shape assertions — only one existing test touches the quick-add route
(`tests/bank_accounts/test_crud_gating.py::test_all_endpoints_404_when_module_off`),
and it only asserts a 404 status when the module is off; it does not inspect
the JSON body. No test needed updating for this fix.

## Test Results

```
pytest tests/bank_accounts/ -q
25 passed, 1 warning in 10.02s
```

```
pytest -k "company_settings or modules_toggle" -q
47 passed, 3090 deselected, 1 warning in 29.10s
```

No regressions from any of the 3 fixes.

## Files Changed

- `app/bank_accounts/templates/bank_accounts/form.html` (Fix 1)
- `app/company_settings/views.py` (Fix 2)
- `app/bank_accounts/views.py` (Fix 3)

No test files required changes — neither the old flash string nor the old
`quick_add` JSON shape (`{'id':...}` alone) was asserted anywhere in `tests/`.

## Concerns

None. All 3 fixes were narrowly scoped, verified against the global CSS
definitions and existing test assertions before editing, and the full
targeted test runs (bank_accounts + company_settings) pass clean.
