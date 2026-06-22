# General Ledger — Traditional T-Ledger Format (Redesign)

**Date:** 2026-06-22
**Status:** Approved (brainstorming complete; user pre-authorized proceeding to plan/implementation)
**Supersedes:** the running-balance presentation from `2026-06-22-general-ledger-design.md`. The
data generator, branch scoping, access gating, source-doc resolver, routes, and filters from that
build are **unchanged**; this redesign changes only the *presentation* (screen, print, exports)
and adds **one** new piece of data (the contra-account per line).

## Summary

Re-present the General Ledger as the **traditional two-sided ("T") ledger book**: per account,
debit entries on the left, credit entries on the right, a total under each side, and the running
balance shown only as **Balance b/f** (opening) at the top and **Balance c/f** (closing) at the
bottom. The "Particulars" column names the **contra-account** (the opposite side of each entry),
the way a manual ledger does. This format applies **everywhere** — on-screen, the printed BIR
book, and the Excel/CSV exports.

This matches the century-stable manual-bookkeeping ledger format and BIR examiner expectations
(each account a section, particulars naming the contra-account, reference back to the source
journal, balances rolling up to the Trial Balance).

## What changes vs. what stays

**Stays (no change):**
- `generate_general_ledger(start, end, branch_id, account_id=None)` query logic, branch scoping,
  posted-only filter, hide-empty rule, opening/closing balance math.
- `_attach_source_links` (the Source column + drill-down), `_gl_params`, the four routes, the
  filter form, the access gate, the reports-index card.
- Each line keeps `running_balance` in the data (now unused by any presentation — retained so
  Task 1's running-balance unit tests stay valid; not displayed anywhere).

**Changes:**
1. The generator adds a **`contra`** string to each line.
2. The screen template, print template, and `_flatten_ledger` (exports) are rebuilt as the
   two-sided T-ledger.
3. Wording: *Opening balance → Balance b/f*, *Closing balance → Balance c/f*, *Period totals →
   Total Debit / Total Credit*.
4. The print page gains a BIR-book header (company name, address, TIN, branch, period).

## Component design

### 1. Contra-account resolution — `app/reports/financial.py`

For each posted ledger line, the **contra** is the account(s) on the **opposite** side of that
line's own journal entry: a debit line's contra is its JE's credit account(s); a credit line's
contra is its JE's debit account(s).

Resolution (batched, no N+1):
- After the per-account sections are built, collect the set of `entry_id`s present across all
  result lines.
- One query loads every `JournalEntryLine` for those entries, joined to `Account` (for the name),
  grouped into `entry_id → [(account_id, account_name, is_debit), …]`. `is_debit` = `debit_amount
  > 0`.
- For each result line, look at the opposite-side accounts of its entry:
  - exactly **one distinct** opposite account (by `account_id`) → `contra = that account's name`;
  - **two or more distinct** → `contra = "Various"`;
  - none (degenerate single-line entry) → `contra = ""`.
- The current line's own account is excluded implicitly (it is on the near side, not the opposite
  side). If an account appears on both sides of one entry, only its opposite-side occurrences
  count toward the contra.

`contra` is added to each line dict (alongside `entry_id`, `entry_number`, `entry_date`,
`entry_type`, `reference`, `description`, `debit`, `credit`, `running_balance`). Pure data —
unit-testable without a request context.

> Display uses the account **name** only (e.g. "Accounts Payable"). The Source column already
> carries the document number, so the contra need not repeat it.

### 2. Screen layout — `app/reports/templates/reports/general_ledger.html`

Per account, replace the single running-balance table with a **side-by-side T-ledger**:

- **Account header:** `code — name` (left) and **Balance b/f: ₱X Dr/Cr** = `opening_balance`
  (right). Dr when `opening_balance >= 0`, Cr otherwise (absolute value), via the existing
  `balance_dr_cr` macro.
- **One table, two halves.** Split the account's lines by side in the template:
  `{% set debit_lines = acct.lines | selectattr('debit') | list %}` and
  `{% set credit_lines = acct.lines | selectattr('credit') | list %}` (a `0.0` amount is falsy, so
  each line lands on exactly one side).
  - **Left (Debit) columns:** `Date · JE# · Source · Particulars · Debit`.
  - **Right (Credit) columns:** `Date · JE# · Source · Particulars · Credit`.
  - Iterate `range(max(debit_lines|length, credit_lines|length))`; for each index render the
    left line if present (else blank `<td>`s) and the right line if present (else blank), so the
    two sides stay aligned even when their row counts differ.
  - JE# links to `journal_entries.view`; Source uses `line.source.url`/`label` (unchanged).
    Particulars renders `line.contra`.
- **Footer:** **Total Debit** = `total_debit` under the left side, **Total Credit** =
  `total_credit` under the right side; then **Balance c/f: ₱X Dr/Cr** = `closing_balance` below.
- **Responsive:** wrap each account table in a `div` with `overflow-x:auto` so narrow screens
  scroll horizontally rather than breaking the two-sided alignment.
- Conventions: literal `₱`, design tokens (`--border`, `--bg`, `--blue`, `--radius`, `--text-2`),
  the account picker and `initSearchSelect`/Choices.js block unchanged.

### 3. Print — `app/reports/templates/reports/general_ledger_print.html`

Same two-sided T-ledger (standalone HTML doc, `window.print()` on load, page-break per account),
plus a **BIR-book page header** at the top:
- **Company name** = `AppSettings.get_setting('company_name', '')`, **address** =
  `company_address`, **TIN** = `company_tin` (all already stored settings; mirror how the APV/CDV/
  CRV print views build their `company` dict).
- **Branch** name (resolve `session['selected_branch_id']` → `Branch`), **General Ledger** title,
  and the **period** (From – To).
- The view passes `company` (name/address/tin) + `branch_name` to the template.

### 4. Exports — `_flatten_ledger` in `app/reports/views.py`

Mirror the T-shape. Columns (`_GL_COLUMNS` / `_GL_HEADERS`) become the 10-column paired set:

```
Date | JE# | Source | Particulars | Debit ‖ Date | JE# | Source | Particulars | Credit
```

Per account, emit: an account-header row (`{code} - {name}` in the first Date cell; a
`Balance b/f` value), then for `i in range(max(len(debit_lines), len(credit_lines)))` a paired row
(left debit-line fields + right credit-line fields, blanks where a side is short), then a
**Total Debit / Total Credit** row, then a **Balance c/f** row. Excel/CSV reuse the same flattened
rows (the `export_to_excel`/`export_to_csv` `item.get(column)` contract is unchanged).

## Data shape (generator return — only the added field)

Each line dict gains `'contra': str`. Everything else is unchanged. Account dicts and the top-level
dict are unchanged (`opening_balance`, `lines`, `total_debit`, `total_credit`, `closing_balance`,
grand totals).

## Ripple effects

- `app/reports/financial.py` — contra resolution added to (or alongside) `generate_general_ledger`.
- `app/reports/views.py` — `general_ledger` and `general_ledger_print` views pass company/branch
  context to the print template; `_flatten_ledger` + `_GL_COLUMNS`/`_GL_HEADERS` reshaped.
- Both templates rebuilt.
- **Tests:** label changes break existing assertions that must be updated:
  - `test_general_ledger_account_filter` uses `resp.data.count(b'Opening balance') == 1` — switch
    to the new section marker (e.g. count `b'Balance b/f'`).
  - `test_general_ledger_csv_export_contains_data` asserts on old labels/format — update to the new
    columns/labels.
  - Any assertion referencing "Opening balance"/"Closing balance"/"Period totals".
- **New tests:**
  - Contra resolution: a 2-line JE → each line's contra is the other account's name; a multi-line
    JE (e.g. Dr Expense / Cr AP + Cr WHT) → the Expense line's contra is "Various"; the AP and WHT
    lines' contra is "Expense" (single opposite).
  - Side-split rendering: an account with both debit and credit lines renders both halves; totals
    and Balance c/f present with the new wording.

## Testing notes

- The contra generator tests build entries directly (mirroring Task 1's `_entry` helper) and assert
  the `contra` string per line — pure unit tests, no request context.
- View/print/export tests reuse the Task 3/4 fixtures and helpers (`_post_je`, `_login`,
  `_select_branch`). The print test additionally seeds a `company_name` setting and asserts it
  appears in the printed page.
- GL remains read-only — no audit assertions apply.

## Out of scope (unchanged from prior deferral)
- Per-account-title access; un-stubbing Trial Balance / Income Statement / Balance Sheet / BIR.
- A separate T-account teaching/visualization view (the running-balance data field is retained but
  no UI consumes it).
