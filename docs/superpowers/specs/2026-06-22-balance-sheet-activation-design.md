# Balance Sheet — Activation + Classified Hierarchy Design

**Date:** 2026-06-22
**Status:** Approved pending spec review (implement with TDD).
**Pattern:** follows the Income Statement hierarchical redesign + the TB/IS activation recipe.

## Context

The Balance Sheet is the last stubbed financial statement. `generate_balance_sheet(as_of_date,
branch_id)` exists (it computes asset/liability/equity balances and the YTD net income via
`generate_income_statement`) but returns FLAT lists; `balance_sheet()` early-returns
`redirect(... under_development)`; the template `reports/balance_sheet.html` exists (flat); nav says
"Soon"; no `balance_sheet` book-permission key; no tests. It is an **as-of-date** report.

The COA supports a classified balance sheet via top-level parent groups:
- Assets (code `1…`): `10000 Current Assets`, `11000 Non-Current Assets`
- Liabilities (code `2…`): `20000 Current Liabilities`, `21000 Non-Current Liabilities`
- Equity (code `3…`): `30000 Equity` (single group) + a computed **Net Income (YTD)** line

## 1. Activation (same recipe as TB/IS)
- Un-stub `balance_sheet()`; `@login_required` only.
- Add `app/users/module_access.py` `MODULE_REGISTRY` (section `'Ledger'`, after `income_statement`):
  `{'key': 'balance_sheet', 'label': 'Balance Sheet', 'section': 'Ledger',
    'endpoints': ('reports.balance_sheet', 'reports.balance_sheet_export_excel',
                  'reports.balance_sheet_print')}` — **no CSV** (financial statements are Excel+Print).
- `base.html` (~line 1175): real `can_access_module(current_user, 'balance_sheet')`-gated nav link
  (drop "Soon", keep icon, `active` via `startswith('reports.balance_sheet')`).
- Reports-index card. As-of-date picker modal (mirror the TB date modal; `var(--card)` bg, no raw hex).

## 2. Generator — rewrite `generate_balance_sheet(as_of_date, branch_id)`

Classified structure by code prefix (1=assets, 2=liabilities, 3=equity) and top-level parent groups.
For each top-level group, sum each postable child's as-of balance (assets debit-positive = debit−credit;
liabilities/equity credit-positive = credit−debit) over posted JEs with `entry_date <= as_of_date`,
branch-scoped; keep non-zero children; group total = Σ children. **Net Income (YTD)** =
`generate_income_statement(date(as_of.year,1,1), as_of, branch_id)['net_income']`, appended as an
equity line `{'code':'', 'name':'Net Income (YTD)', 'amount': …}` and added to equity total.

Return:
```python
{
  'as_of_date': date,
  'sections': [
    {'key':'assets','label':'ASSETS','total':float,
     'groups':[{'label':'Current Assets','total':float,'accounts':[{'code','name','amount'},…]},
               {'label':'Non-Current Assets','total':float,'accounts':[…]}]},
    {'key':'liabilities','label':'LIABILITIES','total':float,'groups':[…]},
    {'key':'equity','label':'EQUITY','total':float,
     'groups':[{'label':'Equity','total':float,'accounts':[…, Net Income (YTD)]}]},
  ],
  'total_assets':float,'total_liabilities':float,'total_equity':float,
  'total_liabilities_equity':float,
  'is_balanced':bool,'difference':float,
}
```
Group label = the top-level group account's name, title-cased (`CURRENT ASSETS` → `Current Assets`).
Empty groups (no non-zero children) are omitted. `is_balanced` = `abs(total_assets −
total_liabilities_equity) < 0.01`. Order: assets, liabilities, equity; groups by code.

## 3. Shared flattening — `balance_sheet_lines(bs)` in `statement_export.py`

Produces render-ready lines (shared by print + Excel). Rule per the section shape:
- **Multi-group section** (Assets, Liabilities): section header (no amount) → for each group: group
  header (no amount) → child accounts → "Total <group>" (single top+bottom rule) → then "TOTAL
  <SECTION>" grand line.
- **Single-group section** (Equity): section header → child accounts (incl. Net Income (YTD)) directly
  (no redundant group header) → "TOTAL EQUITY".
- After all sections: **"TOTAL LIABILITIES AND EQUITY"**.
- Rules: group subtotal → `top_bottom`; `TOTAL ASSETS` and `TOTAL LIABILITIES AND EQUITY` (the two
  balancing grand totals) → `double_bottom`; `TOTAL LIABILITIES` and `TOTAL EQUITY` → `bottom`.
Line dict: `{'kind','label','amount'|None,'indent','rule','group'?}` (`kind` ∈ header/group/account/
group_total/section_total/grand_total).

## 4. Screen — `reports/balance_sheet.html` (collapsible groups)
Render section headers (ASSETS/LIABILITIES/EQUITY, bold), group headers (clickable ▶/▼, loads
collapsed) expanding to child accounts, group subtotals, section totals, TOTAL LIABILITIES AND
EQUITY, and a `.alert.alert-success`/`alert-danger` **balanced / not-balanced** banner (✓ Assets =
Liabilities + Equity, or the difference). Literal `₱`, design tokens, responsive; small toggle
`<script>` (no popups); as-of-date picker modal + Excel/Print buttons.

## 5. Excel — `build_balance_sheet_xlsx(bs, as_of_label, company, branch_name, filename)`
Formatted workbook mirroring the IS builder: company/branch/period header (branch hidden when
`Branch.query.count() <= 1`), two-column Particulars|Amount, indented children, bold group/section
totals, accounting number format, gridlines off, **live formulas** (group total `=SUM(children)`;
section total `=SUM(group totals)`; equity total `=SUM(equity accounts + net income)`; TOTAL
LIABILITIES AND EQUITY `=B{liab}+B{equity}`), `double_bottom` on the two grand totals. Shares
`_xlsx_response`/`_NUM_FMT`/styling with the IS builder.

## 6. Print — `reports/balance_sheet_print.html`
Standalone (window.print()), BIR header (company/TIN/address/branch/as-of), rendered from
`balance_sheet_lines(bs)` with matching rules + the balanced note.

## 7. Tests
- **Generator unit** (`tests/unit/`): seed posted JEs into a current-asset, non-current-asset,
  current-liability, equity account (+ a P&L entry so Net Income YTD ≠ 0); assert group totals,
  section totals, `total_assets`, `total_liabilities`, `total_equity` (incl. net income),
  `total_liabilities_equity`, and `is_balanced` (construct a balanced set); assert empty groups
  omitted and Net Income (YTD) present in equity.
- **View** (`tests/integration/test_balance_sheet_views.py`): renders ASSETS/LIABILITIES/EQUITY,
  group headers, "TOTAL ASSETS", "TOTAL LIABILITIES AND EQUITY", balanced banner; access (staff
  deny/grant, viewer), Excel (`spreadsheetml`) + print (200 + company header), no-redirect.

## Deliberately unchanged
- Dashboard / other consumers of `generate_balance_sheet`: none besides this view (verify with grep).
- BIR reports stay stubbed (the last remaining stubbed report group).

## Verification
Sidebar Balance Sheet link (no "Soon") → classified statement, collapsible groups, balanced banner;
Excel has live formulas + branch hidden (single branch); Print shows the BIR header; reports index
shows the card; user maintenance shows a "Balance Sheet" checkbox.
