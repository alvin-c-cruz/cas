# Sales Journal (SI Journal) — Implementation Plan
**Date:** 2026-06-15
**Branch:** `feature/sales-voucher` (add commits here)
**Goal:** Build a columnar Sales Invoice Journal at `/journals/si` — mirroring the AP Journal at `/journals/ap` exactly — so that all posted Sales Invoices appear in a period-filtered, printable, and exportable columnar ledger grouped by GL account.

---

## Architecture

The AP Journal is the reference implementation. The SI Journal replicates it verbatim with the following substitutions:

| AP Journal | SI Journal |
|---|---|
| `entry_type = 'purchase'` | `entry_type = 'sale'` |
| `PurchaseBill` | `SalesInvoice` |
| `bill_number` / `bill_map` | `invoice_number` / `invoice_map` |
| `vendor_name` / `vendor_invoice_number` / `notes` | `customer_name` / `customer_po_number` / `notes` |
| `_gl_account_ids()` → AP (20101), WHT (20301), input VAT ids | SI-specific: AR (10301 or similar), WHT receivable (10xxx), output VAT ids |
| Voided bills shown with strikethrough | Voided invoices shown with strikethrough |
| `ap_journal_data.py` → `build_columnar()` | `si_journal_data.py` → `build_columnar_si()` |
| `build_ap_journal_xlsx()` | `build_si_journal_xlsx()` |

### Data layer (pure, no Flask request access)
New file: `app/journals/si_journal_data.py`
- Imports `resolve_period` from `ap_journal_data.py` (shared — no duplication).
- `build_columnar_si(posted_entries, draft_entries, ar_account_id, wht_receivable_id, output_vat_ids, voided_invoices=None)` — identical logic to `build_columnar()` in `ap_journal_data.py`.
- `build_si_journal_xlsx(columns, rows, totals, period_label, company_name, branch_name, filename, identity)` — copy of `build_ap_journal_xlsx()` with title changed to "Sales Journal" and header columns "SI No." / "Customer PO" / "Customer" / "Particulars".

### View layer addition (existing blueprint)
File: `app/journals/views.py`
- `_si_gl_account_ids()` — AR account (`10301`), WHT receivable account (`10xxx`), output VAT account ids from `VATCategory.output_vat_account`.
- `_si_journal_context(branch_id)` — queries `JournalEntry` with `entry_type='sale'`, splits posted/draft, fetches voided `SalesInvoice` records, calls `build_columnar_si()`, returns `(period, matrix, invoice_map)`.
- `_si_entry_identity(entry, invoice_map)` — returns `(si_no, customer_po, customer_name, notes)`.
- Three routes: `si_journal()`, `si_journal_print()`, `si_journal_export()`.

### Template layer
Two new templates under `app/journals/templates/journals/`:
- `si_journal.html` — copy of `ap_journal.html` with `ap` → `si` IDs/classes, column headers updated, empty-state message updated.
- `si_journal_print.html` — copy of `ap_journal_print.html` with title "SALES JOURNAL", column headers updated.

### Integration point
File: `app/sales_invoices/templates/sales_invoices/list.html`
- Line 123-124: Replace the "View Journal (Soon)" anchor with `url_for('journals.si_journal')`.
- Add a "Download Journal" button pointing to `url_for('journals.si_journal_export')`.

---

## Key Model Facts

- `JournalEntry.entry_type = 'sale'` (set in `app/sales_invoices/views.py:332`).
- `SalesInvoice.journal_entry_id` FK to `JournalEntry`; reference stored as `invoice_number`.
- `SalesInvoice.customer_name`, `.customer_po_number`, `.notes`, `.status`, `.branch_id`, `.invoice_date`.
- `VATCategory.output_vat_account` relationship for output VAT column IDs (parallel to input VAT for AP).
- AR account code: `'10201'` (Accounts Receivable — Trade). WHT receivable: `'10212'` (Creditable WHT Receivable) — verified against seed_minimal.
- Use `ph_now()` from `app.utils` for timestamps. Never `datetime.now()`.

---

## Column Grouping for SI Journal

The SI journal is a revenue-side journal. Column ordering logic in `build_columnar_si()`:

| Priority | Group | Account | Color in template |
|---|---|---|---|
| 0 | `ar` | Accounts Receivable (AR) | debit (blue) |
| 1 | `output_vat` | Output VAT accounts | credit (red) |
| 2 | `wht_recv` | Creditable WHT Receivable | debit (blue) |
| 3 | `revenue` | All other accounts (Revenue, etc.) | credit (red) |

---

## Task List

---

### Task 1: Create `app/journals/si_journal_data.py` (pure data layer)

**TDD steps:**

1. Write `tests/integration/test_si_journal_columnar.py` first with these tests:
   - `test_build_columnar_si_posted_pivot_and_balance` — one posted SI JE; assert column codes ordered AR → output VAT → WHT recv → revenue; assert `balanced=True`; assert `grand_total == 0`.
   - `test_build_columnar_si_draft_excluded_from_totals` — one posted + one draft SI JE; assert draft-only accounts make no column; assert draft row has `cells == {}`.
   - `test_build_columnar_si_voided_invoice_row` — one voided `SalesInvoice`; assert row present with `is_voided=True`; assert no amounts in totals.

2. Create `app/journals/si_journal_data.py`:
   ```
   resolve_period  # re-exported from ap_journal_data — import and re-use, do not copy
   build_columnar_si(posted_entries, draft_entries, ar_account_id,
                     wht_receivable_id, output_vat_ids, voided_invoices=None)
   build_si_journal_xlsx(columns, rows, totals, period_label, company_name,
                         branch_name, filename, identity)
   ```
   - `build_columnar_si`: identical algorithm to `build_columnar()` in `ap_journal_data.py`, only the column-sort-key and group logic changes (AR=0, output_vat=1, wht_recv=2, other=3).
   - `build_si_journal_xlsx`: copy of `build_ap_journal_xlsx()` with:
     - `ws.title = 'SI Journal'`
     - Preamble title: `'Sales Journal'`
     - Fixed columns: `['Date', 'SI No.', 'Customer PO', 'Customer', 'Particulars']`
     - All other logic identical.

3. Run the unit tests; fix until green.

---

### Task 2: Add `_si_journal_context` and three routes to `app/journals/views.py`

**Files to edit:** `app/journals/views.py`

**Steps:**

1. Add import at the top of the file (alongside the existing ap/cd imports):
   ```python
   from app.journals.si_journal_data import build_columnar_si, build_si_journal_xlsx
   ```

2. Add `_si_gl_account_ids()` helper (after `_gl_account_ids()`):
   ```python
   def _si_gl_account_ids():
       """Return (ar_id, wht_recv_id, output_vat_ids) for SI column grouping."""
       from app.accounts.models import Account
       from app.vat_categories.models import VATCategory
       ar = Account.query.filter_by(code='10201').first()
       wht = Account.query.filter_by(code='10212').first()
       vat_ids = {c.output_vat_account.id for c in VATCategory.query.all() if c.output_vat_account}
       return (ar.id if ar else None, wht.id if wht else None, vat_ids)
   ```

3. Add `_si_journal_context(branch_id)` (after `_cd_journal_context`):
   ```python
   def _si_journal_context(branch_id):
       from app.sales_invoices.models import SalesInvoice
       period = resolve_period(request.args, today=ph_now().date())

       entries = JournalEntry.query.filter(
           JournalEntry.entry_type == 'sale',
           JournalEntry.branch_id == branch_id,
           JournalEntry.entry_date >= period['date_from'],
           JournalEntry.entry_date <= period['date_to'],
       ).order_by(JournalEntry.entry_date).all()
       posted = [e for e in entries if e.status == 'posted']
       drafts = [e for e in entries if e.status == 'draft']

       voided_invoices = SalesInvoice.query.filter(
           SalesInvoice.branch_id == branch_id,
           SalesInvoice.status == 'voided',
           SalesInvoice.invoice_date >= period['date_from'],
           SalesInvoice.invoice_date <= period['date_to'],
       ).order_by(SalesInvoice.invoice_date, SalesInvoice.invoice_number).all()

       ar_id, wht_id, vat_ids = _si_gl_account_ids()
       matrix = build_columnar_si(posted, drafts, ar_id, wht_id, vat_ids,
                                   voided_invoices=voided_invoices)

       refs = [e.reference for e in entries if e.reference]
       invoices = SalesInvoice.query.filter(
           SalesInvoice.invoice_number.in_(refs)).all() if refs else []
       invoice_map = {inv.invoice_number: inv for inv in invoices}
       return period, matrix, invoice_map
   ```

4. Add `_si_entry_identity(entry, invoice_map)`:
   ```python
   def _si_entry_identity(entry, invoice_map):
       inv = invoice_map.get(entry.reference)
       return (
           entry.reference or '—',
           (inv.customer_po_number if inv else '') or '',
           (inv.customer_name if inv else '') or '—',
           (inv.notes if inv else '') or '',
       )
   ```

5. Add three routes (after the CD journal routes):
   ```python
   @journals_bp.route('/journals/si')
   @login_required
   def si_journal():
       branch_id = _branch_id()
       if not branch_id:
           flash('Please select a branch to view journal entries.', 'warning')
           return redirect(url_for('users.select_branch', next=request.url))
       period, matrix, invoice_map = _si_journal_context(branch_id)
       return render_template('journals/si_journal.html',
                              period=period, matrix=matrix, invoice_map=invoice_map)

   @journals_bp.route('/journals/si/print')
   @login_required
   def si_journal_print():
       branch_id = _branch_id()
       if not branch_id:
           flash('Please select a branch.', 'warning')
           return redirect(url_for('users.select_branch', next=request.url))
       from app.branches.models import Branch
       from app.settings import AppSettings
       period, matrix, invoice_map = _si_journal_context(branch_id)
       branch = db.session.get(Branch, branch_id)
       branch_count = Branch.query.count()
       branch_name = branch.name if (branch and branch_count > 1) else None
       company_name = AppSettings.get_setting('company_name') or ''
       return render_template('journals/si_journal_print.html',
                              period=period, matrix=matrix, invoice_map=invoice_map,
                              company_name=company_name, branch_name=branch_name,
                              printed_at=ph_now())

   @journals_bp.route('/journals/si/export')
   @login_required
   def si_journal_export():
       branch_id = _branch_id()
       if not branch_id:
           flash('Please select a branch to export journal entries.', 'warning')
           return redirect(url_for('users.select_branch', next=request.url))
       from app.branches.models import Branch
       from app.settings import AppSettings
       period, matrix, invoice_map = _si_journal_context(branch_id)
       branch = db.session.get(Branch, branch_id)
       branch_count = Branch.query.count()
       branch_name = branch.name if (branch and branch_count > 1) else None
       company_name = AppSettings.get_setting('company_name') or 'Company'
       if period['mode'] == 'month':
           filename = f"SI-Journal-{period['year']}-{period['month']:02d}.xlsx"
       else:
           filename = f"SI-Journal-{period['date_from'].isoformat()}_{period['date_to'].isoformat()}.xlsx"
       return build_si_journal_xlsx(
           columns=matrix['columns'], rows=matrix['rows'], totals=matrix['totals'],
           period_label=period['label'], company_name=company_name,
           branch_name=branch_name, filename=filename,
           identity=lambda e: _si_entry_identity(e, invoice_map))
   ```

---

### Task 3: Create `si_journal.html` template

**File:** `app/journals/templates/journals/si_journal.html`

Copy `ap_journal.html` exactly, then apply these changes:

1. Block title/page title: `Sales Journal` / `Sales Journal`
2. CSS class prefix: rename `ap-jrnl-*` → `si-jrnl-*` throughout (or keep as-is since they are scoped; either approach is fine — consistency favors renaming).
3. Form action: `url_for('journals.si_journal')`
4. Print/export link hrefs: `journals.si_journal_print` / `journals.si_journal_export`
5. Toolbar JS: `fetchAndSwap` URL → `/journals/si`; `exportLink.href` → `/journals/si/export`; `printLink.href` → `/journals/si/print`. Update all `getElementById` IDs (`apFilter` → `siFilter`, `apMode` → `siMode`, `toggleCustom`, `monthFields`, `yearField`, `fromField`, `toField`, `apExportLink` → `siExportLink`, `apPrintLink` → `siPrintLink`, `ap-journal-content` → `si-journal-content`).
6. Meta title inside content div: `Sales Journal`
7. Table headers: `Date | No. | Customer PO | Customer | Particulars | [dynamic account columns]`
8. Row rendering for non-voided: use `invoice_map.get(row.entry.reference)` → `inv`, display `inv.customer_po_number`, `inv.customer_name`, `inv.notes`; link to `url_for('sales_invoices.view', id=inv.id)`.
9. Voided row: display `row.invoice.invoice_date`, `row.invoice.invoice_number`, `row.invoice.customer_po_number`, `row.invoice.customer_name`, `row.invoice.notes`. The `build_columnar_si` voided row stores the SI as key `'invoice'` (analogous to `'bill'` in AP — implement this in the data layer).
10. Empty state message: `No SI entries found for {{ period.label | lower }}.`
11. Column header color: for SI, `ar` and `wht_recv` groups get blue (debit), `output_vat` and `revenue` get red (credit). Update the `{% if col.group in [...] %}` check.

---

### Task 4: Create `si_journal_print.html` template

**File:** `app/journals/templates/journals/si_journal_print.html`

Copy `ap_journal_print.html` exactly, then apply these changes:

1. Block title: `SI Journal Print — {{ period.label }}`
2. CSS class prefix: `apj-` → `sij-` throughout.
3. Document title div: `SALES JOURNAL`
4. Back link: `url_for('journals.si_journal')`
5. Table headers: `Date | SI No. | Customer PO | Customer | Particulars | [dynamic columns]`
6. Row data: same substitutions as `si_journal.html` above (use `invoice_map`, `inv.customer_name`, etc.).
7. Empty state message: `No SI entries found for {{ period.label | lower }}.`
8. Column header colors: same group logic as above (`ar`/`wht_recv` → `debit-col` blue, `output_vat`/`revenue` → `credit-col` red).

---

### Task 5: Wire up the SI list buttons

**File:** `app/sales_invoices/templates/sales_invoices/list.html`

**Lines 122-124 (current):**
```html
<a href="{{ url_for('dashboard.under_development', feature='Sales Journal') }}"
   class="btn btn-secondary btn-sm">View Journal <span style="font-size:10px;opacity:0.7;">(Soon)</span></a>
```

**Replace with:**
```html
<a href="{{ url_for('journals.si_journal') }}"
   class="btn btn-secondary btn-sm">View Journal</a>
<a href="{{ url_for('journals.si_journal_export') }}"
   class="btn btn-secondary btn-sm">Download Journal</a>
```

No other changes to this file.

---

### Task 6: Integration tests

**File:** `tests/integration/test_si_journal_views.py`

Tests to write (mirror `test_ap_journal_columnar.py`):

1. **`test_si_journal_view_renders_account_columns`** — one posted SI JE with AR + revenue accounts; GET `/journals/si?mode=month&year=...&month=...`; assert 200; assert account names in body; assert period label in body.

2. **`test_si_journal_export_returns_xlsx`** — one posted SI JE; GET `/journals/si/export?mode=month&...`; assert 200; assert `Content-Type` starts with `application/vnd.openxmlformats`; assert filename `SI-Journal-YYYY-MM.xlsx` in `Content-Disposition`.

3. **`test_si_journal_view_shows_draft_indicator`** — one draft SI JE; assert `Draft` badge appears in response body.

4. **`test_si_journal_view_shows_voided_invoice`** — one voided `SalesInvoice`; assert invoice_number and `VOIDED` appear in body.

5. **`test_si_journal_print_renders`** — one posted SI JE; GET `/journals/si/print?mode=month&...`; assert 200; assert `SALES JOURNAL` in body.

6. **`test_si_journal_redirects_without_branch`** — GET `/journals/si` with no `selected_branch_id` in session; assert redirect (302).

7. **`test_si_list_view_journal_button_links_to_si_journal`** — GET `/sales-invoices/`; assert `url_for('journals.si_journal')` value (`/journals/si`) present in response body; assert `(Soon)` NOT in body.

Helper pattern (reuse from `test_ap_journal_columnar.py`):
- `_login(client, db_session, branch)` — create accountant user, login, set session branch.
- `_si_entry(branch_id, status, entry_date, number, lines)` — create JE with `entry_type='sale'`.
- `_voided_si(branch_id, invoice_number, invoice_date, customer_name='Customer A')` — create voided `SalesInvoice`.

---

## Execution Order

1. Task 1 (data layer + unit tests) — pure Python, no Flask context needed.
2. Task 2 (view routes) — depends on Task 1.
3. Task 3 (si_journal.html) — depends on Task 2 for URL references.
4. Task 4 (si_journal_print.html) — parallel with Task 3.
5. Task 5 (list.html button wiring) — independent, do any time after routes exist.
6. Task 6 (integration tests) — after all above.

Run `pytest tests/integration/test_si_journal_views.py tests/integration/test_si_journal_columnar.py -v` to verify. Run the full suite (`pytest`) before committing.

---

## Files to Create

- `app/journals/si_journal_data.py`
- `app/journals/templates/journals/si_journal.html`
- `app/journals/templates/journals/si_journal_print.html`
- `tests/integration/test_si_journal_columnar.py`
- `tests/integration/test_si_journal_views.py`

## Files to Edit

- `app/journals/views.py` — add import, `_si_gl_account_ids()`, `_si_journal_context()`, `_si_entry_identity()`, three routes.
- `app/sales_invoices/templates/sales_invoices/list.html` — replace "View Journal (Soon)" link, add "Download Journal" link.

## No Model Changes

No new DB columns, no migrations, no seed changes required. The SI journal reads from existing `JournalEntry`, `JournalEntryLine`, `SalesInvoice`, and `VATCategory` tables.
