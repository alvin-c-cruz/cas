# Owners' reporting basis: VAT folded into income and expense

**Date:** 2026-09-13 · **Status:** approved in brainstorming, awaiting spec review · **Client:** RIC (Rowell Industrial Corporation)

## Why

RIC keeps two views of its financial statements. The GAAP view, which CAS produces today, goes to
stakeholders. The owners read a second view in which output VAT sits inside the related income
account and input VAT inside the related expense account, and the VAT actually remitted to the BIR is
an expense by product line. RIC's chart already carries `VAT EXPENSE - TINCAN` and
`VAT EXPENSE - PLASTIC` (Other Expense) for exactly this purpose; they are unused in CAS so far.

The books of record never change. Posted journal entries are permanent (BIR rule). The owners' view
is a lens over the same posted lines, computed at report time.

## Scope

Reports that gain a `Basis: GAAP | Owners` switch:

- Income Statement
- Income Statement by Product Line
- Balance Sheet
- Cash Flow
- Trial Balance
- General Ledger
- General Journal listing (watermarked "Not a book of record")

Stay GAAP-only, untouched: year-end closing, dashboard, BIR books and VAT return, all posting code.

## 1. Rules of the owners' basis

Applied to posted journal lines only; closing and closing-reversal entries are excluded exactly as
the GAAP reports exclude them today. The set of "VAT accounts" is derived, never hardcoded: the
distinct `output_vat_account_id` values on sales VAT categories, the distinct `input_vat_account_id`
values on purchase VAT categories, and the VAT Payable and Excess Input Tax Carry-Over accounts
assigned on the VAT Settlement page (`vat_payable_account_code`,
`input_vat_carryover_account_code`).

| # | Line on a VAT account | Owners' treatment |
|---|---|---|
| 1 | Output VAT credit whose journal entry is the posted entry of a sales invoice, cash receipt voucher, or sales memo | Moved to the income account of each document line, in proportion to that line's `vat_amount`. A line whose income account is contra-revenue keeps that account. |
| 2 | Input VAT debit whose journal entry is the posted entry of an accounts payable, cash disbursement voucher, or purchase memo | Moved to the account of each document line in proportion to its `vat_amount`. That account is usually an expense; for capital goods it is an asset. Either is "its related account". |
| 3 | Any line of a journal entry whose `entry_type` is `vat_settlement` or `vat_settlement_reversal` | Dropped. Every leg of these entries is a VAT account; they net to zero in this view. |
| 4 | A debit to the VAT Payable account on a cash disbursement voucher or journal voucher (a remittance) | Becomes VAT expense by product line. The amount is split across product categories in proportion to each category's share of output VAT in the most recently settled quarter whose `settled_at` is on or before the payment date. If no settlement precedes it, the payment's own calendar quarter is used. The target account per category comes from Company Settings. |
| 5 | Any other line on a VAT account (a manual journal voucher, a source document that cannot be found, a category with no VAT expense mapping) | Left where it is. Counted as untraced and shown in the reconciliation box with a note. |

Splitting output VAT across document lines uses the document's own `vat_amount` per line. The
posted VAT leg was reconciled to the header by `app/posting/buckets.py`; the remap distributes that
posted leg pro rata to the lines' VAT amounts and absorbs any rounding difference into the largest
line, so the moved total always equals the posted leg to the centavo.

A journal line is linked to its source document through the document's `journal_entry_id` column,
which all six posting paths already populate. A reversal entry (cancel/void) is linked to the
original through `journal_entries.reversed_entry_id`; the lens follows that link to the same
source document and remaps the reversal symmetrically, so a voided invoice moves
nothing net.

**Consequences.** The owners' balance sheet carries no Output Tax, Input Tax, VAT Payable, or
carry-over balances except flagged residue. Owners' net income differs from GAAP net income by
exactly: output VAT moved − input VAT moved − VAT expense recognised. The reconciliation box on every
owners' page shows these terms so the two views tie.

## 2. Company Settings and access

**Storage.** Rows in the existing `app_settings` table, the same mechanism as module toggles and
control accounts. No migration.

| key | value |
|---|---|
| `owners_basis_enabled` | `'1'` / `'0'` |
| `owners_basis_vat_expense_account:<product_category_id>` | account code of the VAT expense account for that category |

**Company Settings card "Owners' View"**, visible to admin roles only:

- Switch: "Enable owners' reporting basis".
- Table: one row per active product category → VAT expense account (select of active expense-type
  accounts). RIC maps TINCAN and PLASTIC to `811001` / `811003`.
- Validation on save: every mapped code must be an active account of an expense type; the switch
  cannot be turned on while any active category is unmapped. The error names the category.
- Audit-logged through `app/audit/utils.py` with a real before/after diff.

**Effective basis for a request** (`app/reports/basis.py`): owners only when all three hold —
the company switch is on, the current user has an admin role, and the request carries
`?basis=owners`. Anything else resolves to GAAP. A non-admin pasting an owners' URL gets GAAP with
no error and no switch shown. This is what keeps stakeholder-facing users from ever reaching the
owners' view.

**Page furniture.** When the feature is on and the user is admin, the seven report pages show a
`Basis: GAAP | Owners` control next to the date and branch filters; it is a plain query parameter so
URLs are shareable and unambiguous. Every owners' page, print view, and Excel export carries the
header line *"Owners' basis: VAT included in income and expenses. Not for external reporting."*
The General Journal listing appends *"Not a book of record."* Each owners' page also shows the
reconciliation box:

```
GAAP net income                 x
+ Output VAT moved to income    x
− Input VAT moved to expense    x
− VAT expense recognised        x
Untraced VAT (flagged)          x   ← with a note per cause
= Owners' net income            x
```

## 3. Architecture

### `app/reports/owners_ledger.py` (new; the only place that knows the rules)

```
remap(lines, *, as_of, branch_id) -> (remapped_lines, RemapSummary)
```

- `lines`: the posted `JournalEntryLine` rows for the period and branch, exactly what the GAAP
  reports already query.
- Returns the same lines with VAT legs re-pointed per §1, as plain namedtuples
  (`LedgerLine(entry_id, entry_number, entry_date, entry_type, description, account_id,
  debit, credit, moved_from_account_id)`), never ORM objects. `moved_from_account_id` is set
  on lines the lens moved so the General Ledger and General Journal can annotate them.
- `RemapSummary` carries: output VAT moved, input VAT moved, VAT expense recognised (by category),
  untraced amount with a list of `(entry_number, account_code, amount, reason)`.
- Pure-read. Loads the source documents it needs in bulk (one query per document type for the
  entry ids in scope), never per line.

### `app/reports/ledger.py` (new; the shared seam)

```
period_balances(start, end, branch_id, basis) -> {account_id: (debit, credit)}
ledger_lines(start, end, branch_id, basis, account_id=None) -> [LedgerLine]
```

- `basis='gaap'` runs the SQL that `_period_balance` and the GL/TB/GJ builders run today. Output for
  GAAP must be byte-identical to the current reports.
- `basis='owners'` runs the same SQL once for the whole period, passes the rows through
  `owners_ledger.remap`, and aggregates. The result is cached on `flask.g` keyed by
  `(start, end, branch_id)` so the income statement's per-account loop and the balance sheet's
  since-inception pass each cost one remap per request.

### Generators gain `basis='gaap'`

`generate_trial_balance`, `generate_income_statement`, `generate_balance_sheet`,
`generate_cash_flow`, `generate_general_ledger` in `app/reports/financial.py`; the General Journal
builder in `app/reports/general_journal_data.py`; `generate_income_statement_by_product_line`
and `generate_sales_by_product_line` (category revenue becomes VAT-inclusive under owners by adding
each item's `vat_amount` to its net). They read balances and lines only through `ledger.py`. Section
layout, rollup, signs and subtotal chains are untouched. `generate_income_statement` returns the
`RemapSummary` under a `basis_summary` key when basis is owners.

### Views and templates

- `_stmt_params()` in `app/reports/views.py` resolves the basis via `basis.py` and passes it to
  generators, exports, and print views.
- Two Jinja macros: `basis_switch()` and `basis_banner(summary)`; the seven templates, their print
  variants, and the two Excel builders in `statement_export.py` include them.

### `app/reports/basis.py` (new, small)

`resolve_basis()` per §2; `owners_basis_enabled()`; `vat_expense_account_for(category_id)`.

### Company Settings

New form section and handler in `app/company_settings/`, following the existing control-account
card pattern.

## 4. Error handling

- The remap never raises inside a report. Every rule that cannot be applied leaves the line in
  place and records a reason in `RemapSummary.untraced`. Reasons: `no_source_document`,
  `manual_entry`, `unmapped_category:<name>`, `no_settlement_reference`.
- Company Settings validation is the only hard stop, and it happens at save time, before the switch
  can be on with an incomplete mapping.
- If the switch is later turned off, `resolve_basis()` returns GAAP for every request; no stale
  cache exists because nothing is stored.

## 5. Testing

Invariants asserted by tests:

1. Remapped lines still balance: Σdebit = Σcredit for every journal entry after the lens.
2. Owners' net income − GAAP net income = output VAT moved − input VAT moved − VAT expense recognised.
3. Owners' balance sheet balances.
4. With the feature off, or basis GAAP, every report's output is identical to today's.

**Unit tests** (`tests/unit/test_owners_ledger.py`) on hand-built ledgers: an invoice with two income
lines at mixed VAT rates; a purchase with input VAT to an asset account; a settlement entry that
vanishes; a remittance split across two categories using a preceding settlement; a remittance with
no settlement before it (falls back to its own quarter); a manual voucher flagged `manual_entry`; a
category with no mapping flagged `unmapped_category`; a voided invoice whose reversal moves nothing net;
rounding on a three-line invoice where pro rata splits do not sum to the posted leg.

**Integration tests** through real HTTP routes (`tests/integration/test_owners_basis_views.py`):
switch absent for non-admin; switch absent with the feature off; non-admin with `?basis=owners`
receives GAAP figures and no banner; admin with `?basis=owners` sees banner, reconciliation box, and
moved figures on page, print, and Excel export for each of the seven reports; General Journal owners'
view shows "Not a book of record"; Company Settings rejects enabling with an unmapped category and
logs an audit diff on success.

**Verification script** `tools/verify_owners_basis.py`: run against a copy of `ric.db`, prints the
reconciliation box for FY2025 and FY2026 year-to-date and the untraced list. The owners confirm the
numbers before the switch is turned on in production.

Register a `owners_basis` marker in `pytest.ini` for the new test modules.

## Out of scope

- WHT or any tax other than VAT.
- Changing how anything posts.
- Persisting owners' figures anywhere.
- Philgen: the feature stays off; no UI or behaviour change there.
