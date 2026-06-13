# Columnar Accounts Payable Journal — Design

**Date:** 2026-06-13
**Status:** Approved (design); pending implementation plan
**Page:** `/journals/ap`

## Goal

Replace the current single-amount AP Journal list with a **GAAP-compliant columnar special journal** that can be viewed on screen, downloaded as Excel, and printed/saved as PDF. Each GL account used in the period becomes its own column; each posted bill is one row; amounts are spread across the account columns and cross-foot to prove debits = credits.

This mirrors the reference format used by Rowell Industrial Corporation's AP Journal (one column per account title, credits in parentheses, totals row at the bottom).

## Background — current state

`app/journals/views.py::ap_journal()` queries `JournalEntry` rows where `entry_type == 'purchase'` for the selected branch and date range, and the template (`app/journals/templates/journals/ap_journal.html`) renders one row per entry showing only `entry.total_credit`. It does **not** read the entry's individual lines.

Each posted purchase bill already produces a balanced `JournalEntry` via `_post_bill_je()` in `app/purchase_bills/views.py`, with `JournalEntryLine` rows:
- one debit line per expense/asset account (net of VAT),
- one debit line per Input VAT bucket,
- one credit line to WHT Payable (if withholding > 0),
- one credit line to Accounts Payable - Trade (total).

The columnar journal is a **read-only pivot of those existing lines** — no change to posting logic.

## Architecture

### Date filter (monthly by default)

Special journals are kept per month, so the filter defaults to a **Month + Year selector** (defaulting to the current month). An optional **"Custom range" toggle** reveals two date inputs for arbitrary `date_from`/`date_to` when a non-monthly span is needed.

- **Month mode** (default): selected month/year derives `date_from` = 1st of month, `date_to` = last day of month. Header reads **"For the month of June 2026"**; export/print filename uses `YYYY-MM` (e.g. `AP-Journal-2026-06.xlsx`).
- **Custom mode**: explicit `date_from`/`date_to` drive the query. Header reads **"From <date_from> to <date_to>"**; filename uses `<from>_<to>`.

Internally both modes resolve to a `date_from`/`date_to` pair, so the query logic below is identical for both. This same filter pattern applies to the future CR and CD journals.

### Data flow

1. Query purchase `JournalEntry` rows for branch + resolved `date_from`/`date_to`, eager-loading `lines` and each line's `account`.
2. Build the **column set**: the union of all accounts referenced by any line in the result set. Columns are ordered "credits first" (see below). Columns appear only if used in the period.
3. For each entry, build a **cell map** `{account_id: signed_amount}` where `signed_amount = debit_amount - credit_amount`. Debits are positive; credits are negative and rendered in parentheses.
4. Compute **per-column totals** across all *posted* entries. The sum of all column totals must equal `0.00` (Σdebits − Σcredits), which is the on-screen/exported balance proof.
5. Pass `columns` (ordered list of `{account_id, code, name, side}`), `rows` (entry + cell map + status), `column_totals`, and the date filter to the template.

### Sign convention

| Account group | Normal side | Rendered |
|---|---|---|
| Accounts Payable - Trade | Credit | `(x.xx)` |
| Withholding Tax Payable (per rate) | Credit | `(x.xx)` |
| Input VAT | Debit | `x.xx` |
| Expense / asset accounts | Debit | `x.xx` |

### Column order (credits first)

Identifier columns on the left: **Date · No. (`bill_number`) · Invoice No. (`vendor_invoice_number`) · Vendor (`vendor_name`) · Particulars (`notes`)**.

Then account columns in fixed priority:
1. **Accounts Payable - Trade** (the AP credit account)
2. **Withholding Tax Payable** columns — one per distinct WHT account used, ordered by code
3. **Input VAT** column(s) — ordered by code
4. **All other accounts** used in the period, ordered by account `code`

Accounts are matched to groups 1–3 by the same account lookups `_post_bill_je()` uses (`_get_gl_accounts()` → AP `20101`, WHT `20301`) and by Input VAT bucket accounts; everything else falls into group 4.

## Particulars source

"Particulars" maps to the bill's **`notes`** field. Notes becomes **required at both the database and the form level** (user-approved model change, 2026-06-13).

**Model change (approved):**
- `PurchaseBill.notes`: `db.Column(db.Text)` → `db.Column(db.Text, nullable=False)`.

**Migration (Alembic, SQLite batch mode):**
1. Backfill existing rows: `UPDATE purchase_bills SET notes = '(No particulars recorded)' WHERE notes IS NULL OR notes = ''` — required so legacy NULL/empty rows do not violate the new NOT NULL constraint.
2. Alter the `notes` column to `nullable=False` via `op.batch_alter_table('purchase_bills')` (SQLite cannot alter a column in place without batch mode).

**Form change:**
- Add a `DataRequired` validator to the notes field in `app/purchase_bills/forms.py`. NOT NULL alone permits an empty string, so the validator enforces actual content on newly created/edited bills.

The journal reads `bill.notes` for each entry (joined via `entry.reference == bill.bill_number`, as the view already does for `bill_map`). Legacy bills backfilled with the placeholder show `(No particulars recorded)` in the Particulars column.

## Draft handling

- **Posted bills**: render full amounts across account columns and **are included in column totals**.
- **Draft bills**: render as a row with identifier columns (Date, No., Invoice No., Vendor, Particulars) plus a **"Draft" status indicator**; their **amount columns are blank and excluded from column totals** (a draft is not yet in the books). This surfaces unposted APVs to the accountant without distorting the journal's balance.
- **Voided / cancelled** bills' entries are excluded (the query already restricts to relevant statuses; voided entries are not `purchase`-posted in totals).

## Components / files

| File | Change |
|---|---|
| `app/journals/views.py` → `ap_journal()` | Resolve month/custom filter into `date_from`/`date_to`; eager-load `lines` + `account`; build ordered `columns`, per-row cell maps, `column_totals`; split posted vs draft; pass period label + filter mode to template. |
| `app/journals/templates/journals/ap_journal.html` | Month/Year selector with a "Custom range" toggle; replace fixed 6-column table with dynamic columnar table; horizontal scroll on screen; add `@media print` landscape stylesheet (pattern from `app/reports/templates/reports/ap_aging.html`); add a Print button (`window.print()`) and an Excel download button. |
| `app/journals/views.py` → new `ap_journal_export()` route | Build the same columnar matrix and emit `.xlsx` via `app/utils/export.py` (custom column assembly — the generic `export_to_excel` takes flat columns, so this route constructs headers/rows to match the on-screen matrix, including the totals row and parenthesised credits). |
| `app/purchase_bills/models.py` | `notes` → `nullable=False` (Particulars). Column type (`Text`) otherwise unchanged. |
| `migrations/versions/<new>.py` | Alembic migration: backfill NULL/empty notes, then `batch_alter_table` set `notes` NOT NULL. |
| `app/purchase_bills/forms.py` | Add `DataRequired` to the notes field (Particulars). |
| Tests | View test (columnar pivot, totals = 0, draft excluded from totals); export route test; form validation test (notes required); migration applies cleanly on a DB with pre-existing NULL notes. |

## Output formats

1. **On-screen columnar view** — replaces the current AP Journal page. Wide tables scroll horizontally.
2. **Excel download** (`.xlsx`) — same columns/rows/totals as the filtered on-screen view.
3. **Print / PDF** — print-friendly landscape via browser print (Ctrl+P → Save as PDF). No server-side PDF library added.

## Edge cases & ripple effects

- **Notes now required (DB + form)**: any fixtures/seed/tests that create bills without notes must be updated to supply notes, or they will fail the NOT NULL constraint and the form validator. The migration backfills legacy rows with `(No particulars recorded)`.
- **Wide tables**: many distinct accounts → many columns. Screen uses horizontal scroll; print uses landscape + reduced font.
- **Excel parity**: the export must use the *same* filter (branch + date range) and the *same* column ordering as the screen so the two always agree.
- **Empty period**: if no entries match, show the existing empty-state message; export produces a header-only sheet.
- **Balance proof**: if posted column totals do not sum to 0.00 (should never happen given `_post_bill_je()` balances every JE), surface it visibly rather than hiding it — a non-zero grand total indicates a data problem worth seeing.

## Out of scope

- Cash Receipts / Cash Disbursements journals (separate future work).
- Server-generated PDF (browser print covers the requirement).
- Changing how purchase bills post to the GL.
