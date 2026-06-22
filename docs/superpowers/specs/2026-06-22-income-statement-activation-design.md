# Income Statement — Activation Design

**Date:** 2026-06-22
**Status:** Approved (implement inline with TDD)
**Mirrors:** `2026-06-22-trial-balance-activation-design.md` (same activation pattern).

## Context

The Income Statement is fully built but switched off, exactly like the Trial Balance was:
`generate_income_statement(start_date, end_date, branch_id)` exists in `app/reports/financial.py`
(returns `period_start/period_end`, `revenue:[{code,name,amount}]`, `total_revenue`,
`expenses:[...]`, `total_expenses`, `net_income`, `net_income_percentage`); the template
`reports/income_statement.html` is complete (revenue/expense sections, net-income banner, a
period-picker modal with **This Month / Last Month / Year to Date / Last Year** quick buttons);
`income_statement_export_excel` exists. Only `income_statement()` early-returns
`redirect(... under_development)` (`views.py:566`) with the real render code dead below it. Nav says
"Soon"; no reports-index card; no `income_statement` book-permission key; no tests.

It is a **date-range** report (start_date → end_date), unlike the as-of-date Trial Balance.

## Approach (mirror of the Trial Balance activation)

### 1. Un-stub the view
Delete the `redirect(...)` in `income_statement()`. Add a shared `_is_params()` returning
`(start_date, end_date, branch_id)` with **year-to-date default** (`start = Jan 1 of current year`,
`end = today`) and `try/except` fallback on bad dates. The render code (read params → branch from
session → `generate_income_statement` → render `reports/income_statement.html`) stays.

> **Default change:** the existing dead code defaulted to month-to-date; switch to **year-to-date**
> to match the General Ledger. The template's quick-period buttons (This Month / Last Month / YTD /
> Last Year) are retained, so both monthly and yearly views remain one click away.

### 2. Access — configurable in user maintenance (GL/TB pattern)
- Change the IS routes from `@accountant_or_admin_required` to `@login_required` only.
- Add to `app/users/module_access.py` `MODULE_REGISTRY` (section `'Ledger'`, after `trial_balance`):
  ```python
  {'key': 'income_statement', 'label': 'Income Statement', 'section': 'Ledger',
   'endpoints': ('reports.income_statement', 'reports.income_statement_export_excel',
                 'reports.income_statement_export_csv', 'reports.income_statement_print')},
  ```

### 3. Outputs — Excel (exists) + CSV + Print
- Keep `income_statement_export_excel`.
- Add `income_statement_export_csv` at `/reports/income-statement/export/csv` (mirror of the Excel
  route via `export_to_csv`; reuse the Excel route's existing combined revenue+expenses row
  flattening + columns/headers).
- Add `income_statement_print` at `/reports/income-statement/print` → standalone print template
  `reports/income_statement_print.html` (no base.html; `window.print()` on load) with a BIR-style
  header (company name/TIN/address + branch + "Income Statement" + the period), revenue section,
  expense section, and net income. Mirror the TB/GL print company/branch plumbing.
- Wire CSV + Print buttons into `income_statement.html` next to the Excel button (each carrying
  `start_date` + `end_date`).

### 4. Template polish (design tokens)
Replace the hardcoded hex in `income_statement.html`:
- Net-income banner `#dcfce7/#bbf7d0/#166534` (positive) and `#fef2f2/#fecaca/#991b1b` (negative) →
  the `.alert.alert-success` / `.alert.alert-danger` classes (token-based).
- Period-picker modal `background: white` → `var(--card)`.
Keep the literal `₱`, the period-picker modal, and the quick-period JS.

### 5. Nav + discoverability
- `app/templates/base.html` (~line 1169): replace the `nav-item--soon` Income Statement link with a
  real `{% if can_access_module(current_user, 'income_statement') %}`-gated link (drop "Soon", keep
  the icon, `active` via `request.endpoint.startswith('reports.income_statement')`).
- Add an Income Statement card to `app/reports/templates/reports/index.html`.

## Deliberately unchanged
- `generate_income_statement` (works; date-range, branch-scoped, 4xxxx revenue / 5xxxx expenses).
- Balance Sheet and BIR stay stubbed.

## Tests (`tests/integration/test_income_statement_views.py`)
- Render: admin with posted revenue+expense JEs → 200, shows a revenue account, an expense account,
  "Net Income", and the positive (success) banner.
- Access: staff without grant → 302; staff with `income_statement` granted → 200; viewer → 200.
- Outputs: Excel → `spreadsheetml`; CSV → `text/csv` + a revenue account code; Print → 200 + company
  header + "Income Statement".
- Un-stub: `/reports/income-statement` returns 200 (not a redirect).
- Default: with no params, the period reflects year-to-date (start = `YYYY-01-01`).

## Verification
Dev server auto-reloads. Logged in: sidebar **Income Statement** link (no "Soon") → renders revenue,
expenses, net income (tokens, no raw hex), defaulting to year-to-date; Excel/CSV/Print all carry the
date range; reports index shows the card; user maintenance shows an "Income Statement" checkbox.
