# Type-Driven Financial Statements — Design Spec

**Date:** 2026-06-24
**Status:** Approved design, pending implementation plan
**Supersedes:** the code-prefix classification in `app/reports/financial.py`
(`_pl_role` 4/501/503/504 convention and `_BS_CATEGORIES` prefix 1/2/3 split).

## Problem

The financial-statement (FS) generators classify accounts by **code prefix**
(`code.startswith('501')` → cost of sales, `startswith('11')` → non-current, etc.)
and derive Income Statement section labels from whichever top-level parent account
happens to carry a role. This is implicit and fragile:

- The Chart of Accounts must carry synthetic "classification" wrapper accounts
  (e.g. `10000 CURRENT ASSETS`) purely so the Balance Sheet has something to group by.
- Section placement is invisible in the account record — it lives in the report code.
- There is no first-class notion of Contra-Revenue, Cost of Goods Sold, Selling vs
  Administrative expense, or Other Income/Expense; everything non-501/503/504 is lumped
  into one "operating expenses" bucket.

## Goal

Make FS classification a **property of the account** (its *type*), so the generators
are **dynamic**: they read each account's `account_type` (+ `classification` for
Current/Non-Current) and place it via a declarative section table. No code prefixes,
no synthetic wrapper accounts, no parent-name label hacks.

## Account model (no schema change)

`Account` already has both columns; we change only their *allowed values* and *usage*:

- **`account_type`** — the single FS-role enum. Allowed values:
  - Balance Sheet: `Asset`, `Liability`, `Equity`
  - Income Statement: `Revenue`, `Contra-Revenue`, `Cost of Goods Sold`,
    `Selling Expense`, `Administrative Expense`, `Other Income`, `Other Expense`,
    `Income Tax Expense`
- **`classification`** — `Current` / `Non-Current`, **required for `Asset` and
  `Liability`, null/ignored for all other types.** Drives the Balance Sheet's
  Current vs Non-Current divisions.
- **`normal_balance`** — stays an explicit per-account field. Defaulted from type
  (see table) but overridable so contra accounts (Accumulated Depreciation,
  Allowance for Doubtful Accounts, Treasury Stock) can flip.

### Type → default normal balance, base category

| account_type | default normal_balance | base category (for legacy/posting helpers) |
|---|---|---|
| Asset | Debit | Asset |
| Liability | Credit | Liability |
| Equity | Credit | Equity |
| Revenue | Credit | Revenue |
| Contra-Revenue | Debit | Revenue |
| Cost of Goods Sold | Debit | Expense |
| Selling Expense | Debit | Expense |
| Administrative Expense | Debit | Expense |
| Other Income | Credit | Revenue |
| Other Expense | Debit | Expense |
| Income Tax Expense | Debit | Expense |

A helper `BASE_CATEGORY: dict[str, str]` (and `Account.base_category` property)
maps each rich type to one of the five legacy bases, so any remaining
`account_type in ('Asset','Expense')`-style logic (normal-balance defaults,
dashboards, posting helpers) keeps working without per-call-site special casing.

## Income Statement (dynamic, declarative)

Driven by an ordered section spec; each entry names the contributing type(s), the
sign, and the running subtotal it closes:

```
IS_SECTIONS = [
  {key:'revenue',        label:'Sales',                        types:['Revenue'],              sign:+1},
  {key:'contra_revenue', label:'Less: Sales Returns & Discounts', types:['Contra-Revenue'],    sign:-1, subtotal:'Net Sales'},
  {key:'cogs',           label:'Cost of Goods Sold',           types:['Cost of Goods Sold'],   sign:-1, subtotal:'Gross Profit'},
  {key:'selling',        label:'Selling Expenses',             types:['Selling Expense'],      sign:-1},
  {key:'admin',          label:'Administrative Expenses',      types:['Administrative Expense'],sign:-1, subtotal:'Operating Income'},
  {key:'other_income',   label:'Other Income',                 types:['Other Income'],         sign:+1},
  {key:'other_expense',  label:'Other Expenses',               types:['Other Expense'],        sign:-1, subtotal:'Income Before Tax'},
  {key:'income_tax',     label:'Income Tax Expense',           types:['Income Tax Expense'],   sign:-1, subtotal:'Net Income'},
]
```

Resulting statement:

```
Sales (Revenue)
  less Sales Returns & Discounts (Contra-Revenue)   = Net Sales
  less Cost of Goods Sold                           = Gross Profit
  less Selling + Administrative Expenses            = Operating Income
  plus Other Income / less Other Expenses           = Income Before Tax
  less Income Tax Expense                           = Net Income
```

- Section labels come from the spec (no more parent-name override).
- Selling + Administrative render under an **Operating Expenses** heading that
  subtotals to Operating Income.
- Closing entries remain excluded (`entry_type NOT IN ('closing','closing_reversal')`).
- `net_income` key/semantics preserved (Balance Sheet + Year-End Close depend on it).

### Income Tax — the answer

Income Tax Expense is its **own `account_type`**, rendered as a single line between
*Income Before Tax* and *Net Income*; it is never folded into operating or other
expenses. Nothing special in the data model — the related balance-sheet accounts are
ordinary: **Income Tax Payable** = Liability/Current, **Creditable/Prepaid Income Tax**
= Asset/Current. The "special" behaviour is purely its fixed position in the subtotal
chain, expressed by its own `IS_SECTIONS` entry.

## Balance Sheet (dynamic)

```
BS_SECTIONS = [
  {key:'assets',      label:'ASSETS',      type:'Asset',     credit_positive:False, divisions:['Current','Non-Current']},
  {key:'liabilities', label:'LIABILITIES', type:'Liability', credit_positive:True,  divisions:['Current','Non-Current']},
  {key:'equity',      label:'EQUITY',      type:'Equity',    credit_positive:True,  divisions:None},
]
```

- Assets and Liabilities are sub-grouped into **Current** and **Non-Current** by the
  `classification` field (with subtotals); Equity is a single division.
- Equity still appends **Retained Earnings** (posted, for closed years) +
  **Net Income (current year)** exactly as today (`latest_closed_year_end` +
  `generate_income_statement`).
- Verifies Assets = Liabilities + Equity (unchanged tolerance).

## Cash Flow (dynamic)

Re-expressed in terms of type/classification instead of code prefix:

- **Investing** = accounts with `account_type=Asset` and `classification=Non-Current`
  (excluding accumulated-depreciation, detected by name as today).
- **Financing** = `account_type=Liability` and `classification=Non-Current`, plus all
  `account_type=Equity`.
- **Operating** = everything else (Current Assets ex-cash, Current Liabilities, all P&L
  types), with the depreciation/amortization add-back unchanged.
- **Cash** detection stays name-based (`'cash' in name.lower()`); depreciation add-back
  stays name-based (`'depreciation' in name.lower()`). Documented carry-over caveat:
  accumulated *amortization* (no "depreciation" in name) still falls to investing — same
  pre-existing latent caveat, surfaced by the reconciliation banner.

## Presentation: roll-up lines + ledger drill-down

1. **Parent = one line; dropdown shows composition.** Each generator returns FS lines as
   parent **groups** carrying the rolled-up total of their postable descendant accounts;
   an expander reveals the child composition. Postable leaves with no parent group render
   as their own line. (IS/BS already have collapsible groups; this generalizes and applies
   it to every section.)
2. **Click a line → ledger popup.** Every FS line is clickable and opens a modal showing
   that account's ledger — date, source, particulars, debit, credit, running balance —
   reusing the General Ledger query, scoped to the account + the statement's period
   (IS: start→end) or as-of date (BS). New lightweight JSON endpoint
   (`/reports/account-ledger?account_id=&start=&end=`) + one shared modal partial used by
   IS, BS, and CF templates. No `confirm()`/`alert()` — custom modal with design tokens.

## Chart of Accounts re-typing (cas_demo.db, current DB only)

The 146-account manufacturing COA (post wrapper-removal) is re-typed:

- Drop the 10 synthetic wrapper accounts (`10000, 11000, 20000, 21000, 30000, 40000,
  50100, 50200, 50300, 50400`); natural groups become top-level.
- Assets: `classification=Current` (10xxx) / `Non-Current` (11xxx).
- Liabilities: `Current` (20xxx) / `Non-Current` (21xxx).
- Revenue accounts → `Revenue`; Sales Returns/Discounts → `Contra-Revenue`.
- COGS + manufacturing cost accounts → `Cost of Goods Sold`.
- Selling/Distribution accounts → `Selling Expense`; G&A accounts → `Administrative Expense`.
- Interest Income / Scrap / Gains / FX Gain / Rental / Misc Income → `Other Income`.
- Interest Expense / Bank Charges / FX Loss / Loss on Sale → `Other Expense`.
- Income Tax Current/Deferred → `Income Tax Expense`.

Hardcoded posting codes are preserved (`10201` AR, `10212` CWT, `20101` AP, `20301` WHT,
`30201` Retained Earnings, `30301` Income Summary). Codes remain for identity/ordering only.

## Account form & list

- Type dropdown offers all 11 `account_type` values (grouped: Balance Sheet / Income
  Statement).
- A **Classification** dropdown (Current / Non-Current) shows only when type is Asset or
  Liability (progressive disclosure), required in that case.
- List/detail badges reflect the richer type; PARENT/leaf derivation unchanged.

## Blast radius (to grep & cover in the plan)

- `app/reports/financial.py` — rewrite IS/BS/CF generators (the core change).
- `app/reports/statement_export.py` — Excel builders must follow the new section
  structure (IS/BS/CF).
- `app/accounts/views.py`, `forms.py`, templates — type choices, classification field,
  normal-balance defaulting, validation.
- `app/dashboard/dashboard_data.py` — any `account_type` base-category assumptions.
- Posting paths — verify none branch on the old 5-value `account_type` (they key on
  account *id* + `normal_balance`); cover with the `base_category` helper if any do.
- Tests: `test_income_statement_generator.py` (label assertions change to spec labels),
  `test_balance_sheet_generator.py`, cash-flow + export tests; new tests for type-driven
  classification, current/non-current split, contra-revenue netting, the account-ledger
  endpoint, and the form's conditional classification field.

## Out of scope / deferred

- Reusable `flask seed-*` command for this COA (current DB only, per earlier decision).
- DIRECT-method cash flow (already deferred).
- Multi-currency, per-account-title access (already deferred).

## Testing strategy (TDD)

Each generator change is driven by unit tests on the generator output (sections, totals,
subtotals, divisions, contra-netting) using in-memory accounts of the new types; the
ledger-drill-down endpoint and the conditional form field get integration tests; a
browser pass verifies the collapsible lines + ledger modal render and the three
statements reconcile against the re-typed demo COA.
