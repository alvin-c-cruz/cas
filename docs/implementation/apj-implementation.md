# Accounts Payable Journal (AP Journal) — Implementation Reference

## Overview

The AP Journal presents all `purchase`-type `JournalEntry` records for a branch and
period in a columnar (spread-sheet style) matrix. Each row is one bill; each column is
one GL account that appears in the underlying JE lines. Voided and draft bills appear
as flagged rows with no amounts. The view supports month and custom date-range filtering,
AJAX in-place refresh, Excel export, and a separate print-preview page.

Blueprint: `journals_bp` registered at `/journals`  
Source files:
- `app/journals/views.py` — routes, context builders
- `app/journals/ap_journal_data.py` — pure data layer (period resolution, matrix builder, Excel writer)
- `app/journals/templates/journals/ap_journal.html` — interactive list view
- `app/journals/templates/journals/ap_journal_print.html` — print-only template

---

## URL Routes

| Method | URL | Handler | Purpose |
|---|---|---|---|
| GET | `/journals/ap` | `ap_journal` | Interactive columnar view |
| GET | `/journals/ap/print` | `ap_journal_print` | A4-landscape print preview |
| GET | `/journals/ap/export` | `ap_journal_export` | Download `.xlsx` file |

All three routes share `_ap_journal_context(branch_id)` which builds the matrix from the
same request args, so the print preview and export always match what is on screen.

---

## Period Resolution (`resolve_period`)

Located in `ap_journal_data.py`. Reads from `request.args`:

| Arg | Default |
|---|---|
| `mode` | `'month'` |
| `year` | current PH year |
| `month` | current PH month |
| `date_from` | — (custom mode only) |
| `date_to` | — (custom mode only) |

Returns a dict with `mode`, `year`, `month`, `date_from` (date), `date_to` (date), `label`.

- **Month mode:** `date_from` = first day, `date_to` = last day of the selected month.
- **Custom mode:** raw ISO strings from `date_from` / `date_to`; falls back to current
  month if either is missing, unparseable, or `date_from > date_to`.

---

## Data Query (`_ap_journal_context`)

```python
# Posted + draft purchase JEs for the branch/period
entries = JournalEntry.query.filter(
    entry_type == 'purchase',
    branch_id == branch_id,
    entry_date >= period['date_from'],
    entry_date <= period['date_to'],
)
posted = [e for e in entries if e.status == 'posted']
drafts = [e for e in entries if e.status == 'draft']

# Voided bills (no JE, but listed with a flag)
voided_bills = PurchaseBill.query.filter(
    branch_id == branch_id,
    status == 'voided',
    bill_date in period range,
)
```

`bill_map` is built by looking up `PurchaseBill` records whose `bill_number` matches any
`entry.reference` in the period — used to pull `vendor_invoice_number`, `vendor_name`,
and `notes` (Particulars) for each row.

---

## Columnar Matrix (`build_columnar`)

Pure function in `ap_journal_data.py` — no Flask imports.

### Column discovery

Columns are built **only from posted entries' accounts**. Draft rows never create new
columns. The column order is:

1. AP account (`20101`) — credit column
2. WHT Payable (`20301`) — credit column
3. Input VAT accounts (any `input_vat_account_id` from `VATCategory`) — credit columns, by code
4. All other accounts (expense/asset debits) — by code

### Row values

For posted rows: `signed = debit_amount − credit_amount` per account per JE.  
Positive values = net debit; negative = net credit (rendered in parentheses in the HTML).

Draft rows: `cells = {}` — no amounts shown, rendered with a "Draft" badge.  
Voided rows: `cells = {}` — no amounts shown, rendered with strikethrough styling.

### Totals

`totals[account_id]` = sum of signed amounts from posted rows only.  
`grand_total` = sum of all column totals. `balanced = (grand_total == 0)` — any non-zero
grand total shows a warning banner (debits ≠ credits in the GL).

### Return value

```python
{
  'columns': [{'account_id', 'code', 'name', 'group'}, ...],
  'rows':    [{'entry', 'bill', 'cells', 'is_draft', 'is_voided'}, ...],
  'totals':  {account_id: Decimal, ...},
  'grand_total': Decimal,
  'balanced': bool,
}
```

---

## Interactive View (AJAX filter)

`ap_journal.html` performs an `XMLHttpRequest` on filter submit and toggle-custom-range
clicks. The fetch sends `X-Requested-With: XMLHttpRequest` but the server currently
returns the full page HTML regardless (no partial-render path). The JS extracts the
`#ap-journal-content` div from the response via `DOMParser` and swaps it in place.

The Print and Export link `href` attributes are updated dynamically to carry the current
filter params.  
`history.pushState` keeps the URL in sync.  
`popstate` handler restores the correct filter state on back/forward navigation.

---

## Print Preview (`ap_journal_print.html`)

- Extends `base.html`.
- `@media print` CSS: hides `nav.sidebar`, `header.topbar`, `.apj-print-actions`,
  `.card-header`; `margin-left: 0` on `.main`; `overflow: visible` on `.apj-scroll`.
- `@page { size: A4 landscape; margin: 10mm }`.
- `thead { display: table-header-group }` — column headers repeat on every printed page.
- `break-inside: avoid` on `tbody tr` — rows do not split across pages.
- Draft rows: yellow background. Voided rows: red background + strikethrough.
- Does **not** show draft/voided badges (only colour coding).
- Company name and branch name are shown in the document header (branch omitted if single-branch).

---

## Excel Export (`build_ap_journal_xlsx`)

Pure function in `ap_journal_data.py`; returns a Flask `Response` with
`Content-Type: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`.

Structure:
1. Preamble rows: company name, optional branch name, "Accounts Payable Journal", period label
2. Header row: `Date | AP No. | Invoice No. | Vendor | Particulars | <account columns…>`
3. Data rows: one per bill. Voided rows get `voided_fill` (light red). Draft rows get
   `draft_fill` (light yellow). Amount cells use `num_fmt = '#,##0.00;(#,##0.00)'`.
4. Blank separator row
5. TOTAL row: `=SUM(…)` formulas per amount column so totals are live in Excel.

Column widths: Date 12, AP No. 22, Invoice No. 22, Vendor 28, Particulars 40, amounts 20 each.

Filename pattern:
- Month mode: `AP-Journal-YYYY-MM.xlsx`
- Custom mode: `AP-Journal-YYYY-MM-DD_YYYY-MM-DD.xlsx`

---

## GL Account Lookup (`_gl_account_ids`)

Uses hard-coded COA codes:
- AP — Trade: `20101`
- WHT Payable — Expanded: `20301`
- Input VAT account IDs: collected from all active `VATCategory.input_vat_account` FK relationships

These same codes are used in the APV module's `_get_gl_accounts()`. Any change to the
COA codes must be reflected in both modules.

---

## Access Control

All three routes: `@login_required` only.  
Branch guard: redirects to branch-select if `session['selected_branch_id']` is not set.

---

## Key Invariants

- Columns are driven by posted entries only — adding a draft with a new account will not
  create a new column until the bill is posted.
- The `grand_total` balance check does not block rendering; it only surfaces a warning
  banner when debits ≠ credits across the matrix.
- The AP Journal reads `JournalEntry.reference` to match back to `PurchaseBill.bill_number`.
  The reference is set to `bill_number` in `_post_bill_je`.
- `notes` on `PurchaseBill` is the "Particulars" column. It is a required field enforced
  at the model level (`nullable=False, default=''`); the form also enforces a non-empty value.
- Voided bills appear in the period of their `bill_date`, not the void date.
- Draft entries appear in the period of their `entry_date` (bill date at creation).
