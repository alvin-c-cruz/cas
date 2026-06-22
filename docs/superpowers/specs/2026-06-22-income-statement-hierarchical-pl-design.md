# Income Statement — Hierarchical P&L Redesign

**Date:** 2026-06-22
**Status:** Approved (implement with TDD; COA account creation approved)
**Supersedes presentation of:** `2026-06-22-income-statement-activation-design.md` (the flat
revenue/expenses list). The route wiring, access gate, CSV/Print routes, and nav/index card from
that activation **stay**; this redesign changes the **generator return shape**, the **template**,
the **exports**, and the **print** layout, and adds one COA group.

## Context

The just-activated Income Statement lists revenue (4xxxx) and expense (5xxxx) leaf accounts flat.
The owner wants a proper multi-level P&L driven by the **parent-account hierarchy**, with each
parent group shown first and expandable to its children:

```
Revenue                          [40000]
Less: Cost of Construction       [50100]
   = Gross Profit
Less: Operating Expenses         [50200]
   = Operating Income (Loss)
Less: Financial Expenses         [50300]      (non-operating, separate line — owner's choice)
   = Income Before Income Tax
Less: Income Tax Expense         [50400]      (new account — owner approved)
   = NET INCOME (LOSS)
```

The COA's `classification` field is empty, so the structure is driven by the top-level parent
groups and their codes. Confirmed COA (cas_demo.db): top-level groups `40000 REVENUE`,
`50100 Cost of Construction`, `50200 Operating Expenses`, `50300 Financial Expenses`, each with
leaf children.

## 1. New COA account (approved)

Create (cas_demo.db, via the `Account` model with an audit entry — propose-then-create is already
approved):
| Code | Name | Parent | account_type | normal_balance | Postable |
|---|---|---|---|---|---|
| `50400` | Income Tax Expense | (top-level) | Expense | Debit | No (group header) |
| `50401` | Income Tax Expense | `50400` | Expense | Debit | Yes (leaf) |

A top-level account is a non-postable group (per the hierarchy rule), so income tax is posted to
the `50401` leaf. On instances without these accounts (ric.db, real CAS) the Income Tax section is
simply empty/₱0 — the generator must degrade gracefully.

## 2. Generator — rewrite `generate_income_statement(start_date, end_date, branch_id)`

Walk the **top-level income/expense parent groups** and classify each into a P&L role by **code
prefix** (extends the existing `4%`/`5%` convention):

| Role key | Match | Subtotal after it |
|---|---|---|
| `revenue` | `account_type == 'Revenue'` (code `4…`) top-level group(s) | — |
| `cost_of_sales` | top-level expense group, code starts `501` | **Gross Profit** = revenue − cost_of_sales |
| `operating_expenses` | code starts `502` **(and any expense group not matching another role)** | **Operating Income** = gross_profit − operating_expenses |
| `financial` | code starts `503` | **Income Before Income Tax** = operating_income − financial |
| `income_tax` | code starts `504` | **Net Income** = income_before_tax − income_tax |

For each role: gather the matching top-level parent group(s); for each **postable child** compute
its period amount (revenue: `credit − debit`; expense: `debit − credit`) from posted JE lines in
`[start_date, end_date]`, branch-scoped (reuse the existing per-account summation); keep children
with a non-zero amount; section `total` = sum of kept children. A role with no matching group/
accounts yields an empty section with `total = 0` (so subtotals still compute).

Return shape:
```python
{
  'period_start': date, 'period_end': date,
  'sections': [
    {'key': 'revenue',            'label': 'Revenue',              'deduction': False,
     'total': float, 'accounts': [{'code': str, 'name': str, 'amount': float}, ...]},
    {'key': 'cost_of_sales',      'label': 'Cost of Construction', 'deduction': True,  'total': float, 'accounts': [...]},
    {'key': 'operating_expenses', 'label': 'Operating Expenses',   'deduction': True,  'total': float, 'accounts': [...]},
    {'key': 'financial',          'label': 'Financial Expenses',   'deduction': True,  'total': float, 'accounts': [...]},
    {'key': 'income_tax',         'label': 'Income Tax Expense',   'deduction': True,  'total': float, 'accounts': [...]},
  ],
  'gross_profit': float,
  'operating_income': float,
  'income_before_tax': float,
  'net_income': float,
  'net_income_percentage': float,   # net_income / revenue * 100 (0 if revenue 0)
}
```
`label` is the matching parent group's name (falls back to a sensible default per role if the group
is absent). Section order is fixed (revenue → cost_of_sales → operating_expenses → financial →
income_tax). `generate_balance_sheet` calls `generate_income_statement` for YTD net income — its
consumer reads `['net_income']`, which is preserved, so the Balance Sheet is unaffected.

## 3. Template — `reports/income_statement.html` (collapsible P&L)

Render one block per non-empty section + the subtotal rows, in order:
- **Section (parent) row:** a clickable row showing a ▶/▼ toggle, `Less:` prefix when `deduction`,
  the section `label`, and the section `total` (right-aligned). Loads **collapsed** (parents only).
- **Child rows (hidden until expanded):** `code` · `name` · `amount`, indented.
- **Subtotal rows** after the mapped sections: **Gross Profit**, **Operating Income (Loss)**,
  **Income Before Income Tax**, and the final **NET INCOME (LOSS)** banner (the existing
  `.alert.alert-success`/`alert-danger` net-income banner, now fed `net_income`, with the net-margin
  %). Subtotal rows are styled distinctly (bold, top border) and are not collapsible.
- Toggle via a small inline `<script>` (no popups); collapsed by default. Keep the period header,
  the Excel/CSV/Print buttons, and the period-picker modal (with its quick-period presets) unchanged.
- Conventions: literal `₱`, design tokens, responsive.

## 4. Exports — `_is_flatten` rewrite (Excel + CSV)

Emit flat rows mirroring the statement, columns `['line', 'code', 'name', 'amount']` / headers
`['Line', 'Code', 'Account', 'Amount']`:
- per section: a header row (`line` = (`Less: `)label, `amount` = section total), then one row per
  child (`code`, `name`, `amount`), then the relevant subtotal row (`line` = subtotal name, `amount`
  = value). Final Net Income row. Both Excel and CSV reuse this flattening.

## 5. Print — `reports/income_statement_print.html`

Rewrite to the sectioned P&L: BIR header (company/branch/period) + each section (label, children,
total) + the subtotal rows + Net Income. Children shown expanded (print is static).

## 6. Tests — rewrite `tests/integration/test_income_statement_views.py` + add generator units

- **Generator unit** (`tests/unit/`): seed posted JEs hitting a revenue child (40101), a cost-of-
  sales child (50101), an operating child (50210), a financial child (50301), and an income-tax
  child (50401); assert the section totals, and `gross_profit` / `operating_income` /
  `income_before_tax` / `net_income` equal the hand-computed values; assert children with zero
  activity are excluded; assert an absent income-tax account yields a zero `income_tax` section
  without breaking subtotals.
- **View:** renders the section parent rows (e.g. "Cost of Construction", "Gross Profit",
  "Operating Income", "NET INCOME") and the child accounts are present in markup (collapsed);
  positive banner = `alert-success`. Access/exports/print/no-redirect/YTD-default tests from the
  activation are kept (updated for the new structure where they assert content).

## Verification
Dev server auto-reloads. Logged in: the Income Statement shows the parent groups with subtotals
(Gross Profit, Operating Income, Income Before Tax, Net Income), loads collapsed, and expands each
parent to its children on click; Excel/CSV/Print reflect the sectioned structure; the new
`50400/50401` Income Tax Expense accounts appear in the Chart of Accounts.
