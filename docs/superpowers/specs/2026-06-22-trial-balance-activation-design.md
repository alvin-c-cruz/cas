# Trial Balance — Activation Design

**Date:** 2026-06-22
**Status:** Approved (brainstorming complete; implement inline with TDD)

## Context

The Trial Balance is fully built but switched off: `generate_trial_balance(as_of_date, branch_id)`
exists in `app/reports/financial.py`, the template `app/reports/templates/reports/trial_balance.html`
is complete (table + totals + balanced/not-balanced banner + as-of-date picker modal + Excel link),
and `trial_balance_export_excel` works — but the `trial_balance()` view early-returns
`redirect(url_for('dashboard.under_development', feature='Trial Balance'))` (`views.py:503`) with the
real render code dead below it. The nav still says "Soon", there's no reports-index card, no
`trial_balance` book-permission key, and no tests. This activates it, matching the General Ledger
wiring exactly.

## Approach

### 1. Un-stub the view
Delete the `redirect(...)` line in `trial_balance()`. The existing body (read `as_of` param →
default today, branch from `session['selected_branch_id']`, `generate_trial_balance`, render
`reports/trial_balance.html`) is correct as-is.

### 2. Access — configurable in user maintenance (GL pattern)
- Change the three TB routes from `@accountant_or_admin_required` to `@login_required` only
  (matching `reports.general_ledger` / aging reports). The global `before_request` module gate then
  governs access.
- Add to `app/users/module_access.py` `MODULE_REGISTRY` (section `'Ledger'`, after `general_ledger`):
  ```python
  {'key': 'trial_balance', 'label': 'Trial Balance', 'section': 'Ledger',
   'endpoints': ('reports.trial_balance', 'reports.trial_balance_export_excel',
                 'reports.trial_balance_export_csv', 'reports.trial_balance_print')},
  ```
  Staff become grantable via the user-edit form (driven by the registry); admin/accountant/viewer
  always allowed.

### 3. Outputs — Excel (exists) + CSV + Print
- Keep `trial_balance_export_excel`.
- Add `trial_balance_export_csv` at `/reports/trial-balance/export/csv` — mirror of the Excel route
  using `export_to_csv(trial_balance_data['accounts'], columns, headers, filename)` with the same
  `columns = ['code', 'name', 'debit_balance', 'credit_balance']` / `headers`.
- Add `trial_balance_print` at `/reports/trial-balance/print` → a standalone print template
  `reports/trial_balance_print.html` (does not extend base.html; `window.print()` on load) with a
  BIR-style header: company name (`AppSettings.get_setting('company_name')`), branch name, "Trial
  Balance", and "As of {date}". Mirror the GL print view's company/branch context plumbing.
- Wire CSV + Print buttons into `trial_balance.html` next to the existing Excel button (each
  carrying `?as_of={{ as_of_date.isoformat() }}`).

### 4. Template polish (design tokens)
Replace the hardcoded hex in `trial_balance.html`:
- Balanced banner `background:#dcfce7;border:#bbf7d0;color:#166534` → the existing
  `var(--alert-success-bg)` / `var(--alert-success-text)` tokens (or the `.alert.alert-success`
  class).
- Not-balanced banner `#fef2f2/#fecaca/#991b1b` → `var(--alert-error-bg)` / `var(--alert-error-text)`
  (or `.alert.alert-danger`).
- Modal `background: white` → `var(--card)`.
Keep the literal `₱`, the date-picker modal, and the structure.

### 5. Nav + discoverability
- `app/templates/base.html` (~line 1184): replace the `nav-item--soon` Trial Balance link with a
  real link gated by `{% if can_access_module(current_user, 'trial_balance') %}`, drop the "Soon"
  badge, keep the ⚖️ icon, `active` keyed on `request.endpoint == 'reports.trial_balance'`.
- Add a Trial Balance card to `app/reports/templates/reports/index.html` (alongside AR/AP aging +
  General Ledger).

## Deliberately unchanged
- `generate_trial_balance` (works; as-of-date, branch-scoped, skips zero-balance accounts).
- The other still-stubbed statements (Income Statement, Balance Sheet, BIR) stay stubbed.

## Tests
- View: admin with posted JEs → 200, shows the table + a balanced banner (`is_balanced`).
- Access: staff without grant → 302 (module gate, staff assigned to branch first, mirroring the GL
  staff-gate test); staff **with** `trial_balance` granted → 200; viewer → 200.
- Outputs: Excel route → `spreadsheetml` content-type; CSV route → `text/csv` + contains an account
  code; Print route → 200 + company header + "Trial Balance".
- Un-stub: a request to `/reports/trial-balance` no longer redirects to `under-development`.

## Verification
Dev server auto-reloads. Logged in at `http://127.0.0.1:5050`:
1. Sidebar **Trial Balance** link (no "Soon") → `/reports/trial-balance` renders the table, totals,
   and the balanced/not-balanced banner (tokens, no raw hex).
2. Excel, CSV, and Print buttons all work and carry the `as_of` date.
3. Reports index shows a Trial Balance card.
4. In user maintenance, a staff user shows a "Trial Balance" checkbox under Ledger.
