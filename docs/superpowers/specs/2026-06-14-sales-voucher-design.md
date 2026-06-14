# Sales Voucher (SV) — Design Spec
**Date:** 2026-06-14
**Blueprint:** APV (`app/purchase_bills/`) mirrored on the sales/receivables side
**Approach:** Upgrade the existing `app/sales_invoices/` skeleton in place

---

## Overview

The Sales Voucher (SV) module is the accounts-receivable counterpart of the AP Voucher. It records revenue transactions against customers, generates a linked journal entry on save, and follows the same draft → posted → cancelled lifecycle as APV.

Key design decisions:
- **VAT-inclusive** line items (single `amount` field; VAT extracted, not added)
- **WHT on the invoice** (creditable WHT receivable — customer deducts on payment)
- **No `sent` status** (deferred to a later module)
- Attachments, print, export, and summary cards all mirror APV

---

## Section 1: Model Changes

### 1.1 `SalesInvoice` — fields to add

| Field | Type | Notes |
|---|---|---|
| `journal_entry_id` | FK → `journal_entries.id`, nullable | Linked JE created on save |
| `total_before_wt` | Numeric(15,2), default 0 | Subtotal before WHT deduction |
| `withholding_tax_amount` | Numeric(15,2), default 0 | Sum of all line WHT amounts |
| `vat_override` | Boolean, default False | Manual VAT override flag |
| `wt_override` | Boolean, default False | Manual WHT override flag |
| `cancel_reason` | String(500), nullable | Required on cancel action |
| `customer_po_number` | String(100), nullable | Customer's PO reference (optional) |
| `customer_po_date` | Date, nullable | Customer's PO date (optional) |

**Fields to change:**
- `notes` → `nullable=False, default=''` (currently nullable=True)
- `line_items` lazy → `'select'` (currently `'dynamic'`; causes issues with eager loading)

**Fields to remove:**
- `sent_at`, `sent_by_id`, `sent_by` (no `sent` status in this module)

**`calculate_totals()` rewritten** — VAT-inclusive model (VAT extracted, not added):
```
subtotal      = sum of all line amounts (VAT-inclusive)
vat_amount    = sum of line VAT amounts (extracted)
withholding_tax_amount = sum of line WHT amounts
total_before_wt = subtotal
total_amount  = subtotal − withholding_tax_amount
balance       = total_amount − amount_paid
```

**`journal_entry` relationship** added:
```python
journal_entry = db.relationship('JournalEntry', foreign_keys=[journal_entry_id])
```

### 1.2 `SalesInvoiceItem` — fields to remove / add

**Remove:** `quantity`, `unit_price`

**Keep:** `description`, `amount`, `vat_category`, `vat_rate`, `line_total`, `vat_amount`, `account_id`

**Add:**

| Field | Type | Notes |
|---|---|---|
| `wt_id` | FK → `withholding_tax.id`, nullable | Selected WHT code |
| `wt_rate` | Numeric(5,2), nullable | Snapshot of rate at time of entry |
| `wt_amount` | Numeric(15,2), default 0 | Computed WHT on net base |

**`calculate_amounts()` rewritten** — extract VAT, compute WHT on net base (identical to `PurchaseBillItem`):
```
vat_rate   = item.vat_rate / 100
net_base   = amount / (1 + vat_rate)   if vat_rate > 0 else amount
line_total = amount
vat_amount = amount − net_base
wt_amount  = net_base × wt_rate / 100
```

**`to_dict()` updated** — remove `quantity`/`unit_price`, add `wt_id`, `wt_rate`, `wt_amount`.

### 1.3 `SalesInvoiceAttachment` — new model

Mirrors `PurchaseBillAttachment` exactly. Table: `sales_invoice_attachments`.

Fields: `id`, `invoice_id` (FK → sales_invoices), `original_filename`, `stored_filename` (uuid4 hex + ext), `mime_type`, `file_size` (bytes), `uploaded_by_id` (FK → users), `uploaded_at`.

Properties: `is_image` (mime_type starts with `image/`), `file_size_human`.

### 1.4 `VATCategory` — one field to add

| Field | Type | Notes |
|---|---|---|
| `output_vat_account_id` | FK → `accounts.id`, nullable | Output VAT GL account for sales JEs |

Relationship: `output_vat_account = db.relationship('Account', foreign_keys=[output_vat_account_id])`

`to_dict()` updated to include `output_vat_account_id`, `output_vat_account_code`, `output_vat_account_name`.

### 1.5 Migration

Single Alembic migration covering all the above:
- ADD columns to `sales_invoices`
- ADD columns to `sales_invoice_items`
- DROP columns `quantity`, `unit_price` from `sales_invoice_items`
- CREATE table `sales_invoice_attachments`
- ADD column `output_vat_account_id` to `vat_categories`

---

## Section 2: Journal Entry Logic

Five helper functions in `views.py`.

### 2.1 `_get_gl_accounts()`
Returns `{'ar': Account, 'wt': Account}`.
- AR - Trade: account code `10201`
- Creditable WHT Receivable: exact code confirmed from COA during implementation

### 2.2 `_output_vat_buckets(invoice)`
Mirror of APV's `_input_vat_buckets()`. Groups output VAT by VAT category, using `VATCategory.output_vat_account`. Applies VAT override difference to the largest bucket. Raises `ValueError` if a VAT-bearing line's category has no `output_vat_account` configured.

### 2.3 `_post_invoice_je(invoice, user_id)`
Creates the sales JE. Debits and credits are the **reverse of APV**:

| Line | APV | Sales Voucher |
|---|---|---|
| Revenue/Expense | Dr Expense (net base) | Cr Revenue (net base) |
| VAT | Dr Input VAT (per bucket) | Cr Output VAT (per bucket) |
| WHT | Cr WHT Payable | Dr Creditable WHT Receivable |
| Control | Cr Accounts Payable | Dr Accounts Receivable |

- `entry_type = 'sale'`
- JE created as `draft` when invoice is draft; promoted to `posted` by the post route
- Rounding residual absorbed into the first revenue line (same pattern as APV)
- Raises `ValueError` if AR account not found or if a VAT-bearing line has no output VAT account

### 2.4 `_create_reversal_je(invoice, reversal_date, user_id, label)`
Replaces the existing `_create_invoice_void_je()` in the skeleton. Swaps debits/credits from the **stored JE** — identical logic to APV's `_create_reversal_je()`. Safer than reconstructing from scratch (handles overrides and residuals correctly). Used by both cancel and void routes. `entry_type = 'reversal'`, `is_reversing = True`.

### 2.5 `_build_je_preview(invoice)`
For the detail view. If posted: reads from `invoice.journal_entry.lines`. If draft: computes the same entries `_post_invoice_je` would create. Returns list of `{code, name, debit, credit}` dicts.

---

## Section 3: List View & Summary Cards

### 3.1 `compute_invoices_summary(branch_id)` — `utils.py`
Mirrors `compute_bills_summary()`. Returns:
- `outstanding_total/count` — open AR balance (posted + partially_paid)
- `overdue_total/count` — past due date, still open
- `due_soon_total/count` — due within 7 days
- `draft_count` — drafts not yet posted

### 3.2 `_filtered_invoices_query(include_ids=False)`
Branch-scoped query builder. Filter args: `status`, `customer`, `q` (invoice number or customer name), `date_from`, `date_to`. When `include_ids=True`, a valid `ids=` param overrides all other filters (export-only).

### 3.3 `list_invoices()` route
Replaces current redirect-to-under-development. Pagination: 50/page. Passes `summary`, `customers`, filter state to template.

### 3.4 List template
- Four summary cards: Outstanding, Overdue, Due Soon, Drafts
- Filter bar: status tabs, customer dropdown, search box, date range
- Table: `Invoice # | Date | Due | Customer | Subtotal | VAT | WHT | Total | Balance | Status | Actions`
- Export buttons (Excel, CSV), "+ Enter Invoice" button
- Pagination footer with "Showing X of Y"

---

## Section 4: Create & Edit Form

### 4.1 `generate_invoice_number()`
Fixed to use `ph_now()`. Format: `SI-YYYY-NNNN` (annual reset, no month).

### 4.2 `create()` route — `staff_or_above_required`
1. Validate invoice date against closed periods
2. Snapshot customer name / TIN / address
3. Parse line items JSON; call `calculate_amounts()` per item
4. Call `calculate_totals()`
5. Apply VAT/WHT overrides (`_apply_overrides()`)
6. `db.session.add(invoice)` + `flush()` to get ID
7. Call `_post_invoice_je()`, link `journal_entry_id`
8. Commit; `log_create`

### 4.3 `edit()` route — `staff_or_above_required`
- Draft-only guard
- Delete old line items; rebuild from JSON
- Delete old JE (FK-null-then-delete pattern), create fresh JE
- Commit; `log_update`

### 4.4 Form template
Mirrors `purchase_bills/form.html`. Label swaps:

| APV label | SV label |
|---|---|
| Vendor | Customer |
| AP Voucher # | Invoice # |
| Bill Date | Invoice Date |
| Vendor Invoice # | Customer PO # (optional) |
| Vendor Invoice Date | Customer PO Date (optional) |
| Enter Bill / Enter First Bill | Enter Invoice / Enter First Invoice |

Line item table columns: Description, Amount, VAT Category, WHT Code, Account Title.
Pickers: Customer (Choices.js, code+name), VAT category (code only), WHT (code only), Account (code+name, groups disabled).
Invoice Summary panel: same CSS grid decimal alignment as APV Bill Summary.

**Customer PO # and Date are optional** — no posting guard applies.

---

## Section 5: Detail View

### 5.1 `view()` route
Fetches invoice via `_get_invoice_or_404()`, builds `je_entries` via `_build_je_preview()`, reads `sv_print_access` from `AppSettings`.

### 5.2 Detail template
**Header panel:** Invoice #, Invoice Date, Due Date, Status badge, Customer name/TIN/address, Customer PO # / Date (if present), Payment Terms, Reference, Notes.

**Line items table:** Description, Amount, VAT Category, VAT Amount, WHT Code, WHT Amount, Account.

**Invoice Summary panel (CSS grid, decimal-aligned):**
```
Subtotal            ₱ xxx,xxx.xx
VAT                 ₱   x,xxx.xx  [pencil if override]
                    ──────────────
Total Before WHT    ₱ xxx,xxx.xx
WHT                 ₱   x,xxx.xx  [pencil if override]
                    ══════════════
Total               ₱ xxx,xxx.xx
Amount Paid         ₱   x,xxx.xx
Balance Due         ₱ xxx,xxx.xx
```

**JE Preview section:** collapsible table — account code, name, debit, credit. Label: "Journal Entry Preview" (draft) / "Posted Journal Entry" (posted).

**Action buttons (role-gated):**
- Draft: Edit, Post, Void
- Posted: Cancel, Print
- Cancelled/Voided: Print only (if `sv_print_access` allows)

Void and Cancel open custom HTML modals (CSRF token, reason textarea, reversal date). No `confirm()` or `alert()`.

---

## Section 6: Lifecycle

### Status transitions
```
draft ──[post]──→ posted ──[cancel]──→ cancelled
  └──[void]──→ voided
```

### 6.1 `post()` — `staff_or_above_required`
- Guard: status must be `draft`
- No mandatory field check (Customer PO is optional)
- Sets `status='posted'`, `posted_by_id`, `posted_at`
- Promotes linked JE to `posted`
- Audit: `action='post'`

### 6.2 `cancel()` — `accountant_or_admin_required`
- Guard: status must be `posted`; `amount_paid` must be 0
- Requires `cancel_reason` (min 10 chars) + `reversal_date`
- Calls `_create_reversal_je(invoice, reversal_date, user_id, label='Cancel')`
- Sets `status='cancelled'`, `cancelled_at`, `cancel_reason`
- Audit: `action='cancel'`

### 6.3 `void()` — `staff_or_above_required`
- Guard: status must be `draft`
- Requires `void_reason` (min 10 chars) + `reversal_date`
- Deletes linked draft JE (FK-null-then-delete)
- Collects attachment file paths, deletes DB rows, commits, then deletes files from disk (same order as APV void)
- Sets `status='voided'`, `voided_at`, `voided_by_id`, `void_reason`
- Audit: `action='void'`

---

## Section 7: Print

### 7.1 `print_invoice()` route
Fetches invoice, sorts JE lines: revenue credits → output VAT credits → debits (AR + WHT), each sorted by account code. Reads `company_name`, `company_address`, `company_tin` from `AppSettings`. Passes `printed_at = ph_now()`. Respects `sv_print_access` setting.

### 7.2 Print template
Standalone page (no nav/sidebar). Content:
- Company header (name, address, TIN)
- **SALES INVOICE** title + invoice number
- Invoice Date, Due Date, Customer PO # (if present)
- Customer block: name, TIN, address
- Line items table: Description, Amount, VAT Rate, VAT Amount, WHT, Net
- Summary totals
- JE lines table (internal reference)
- Notes
- Signature lines: Prepared by / Approved by / Received by

`@media print` hides browser chrome; auto-print on load.

---

## Section 8: Export

### Columns
`invoice_number`, `invoice_date`, `due_date`, `customer_name`, `customer_tin`, `customer_po_number`, `subtotal`, `vat_amount`, `withholding_tax_amount`, `total_amount`, `amount_paid`, `balance`, `status`

Both `export_excel()` and `export_csv_route()` use `_filtered_invoices_query(include_ids=True)`. Filenames timestamped with `ph_now()`. Both actions audit-logged.

---

## Section 9: Attachments

Storage path: `instance/uploads/sales_invoices/<invoice_id>/<uuid4_hex>.<ext>`

| Route | Method | Guard | Condition |
|---|---|---|---|
| `/<id>/attachments/upload` | POST | `staff_or_above` | Draft only |
| `/attachments/<att_id>/download` | GET | `login_required` | Any non-voided status |
| `/attachments/<att_id>/preview` | GET | `login_required` | Images only, served inline |
| `/attachments/<att_id>/delete` | POST | `accountant_or_admin` | Draft only |

Allowed types: `.png`, `.jpg`, `.jpeg`, `.gif`, `.webp`, `.pdf`, `.doc`, `.docx`, `.xls`, `.xlsx`, `.csv`, `.txt`. SVG excluded.

Preview served with `Content-Security-Policy: default-src 'none'; sandbox`.

Void deletes all attachment files from disk (after DB commit). Upload/delete audit-logged.

---

## Section 10: Wiring

### `app/__init__.py`
- Add `SalesInvoiceAttachment` to model import block (migration autodetect)
- `sales_invoices_bp` already registered — no change

### `base.html`
Confirm sidebar nav entry points to `sales_invoices.list_invoices` and sits under the Receivables/Sales section. No change if already wired.

### `VATCategory` form + views
- `vat_categories/forms.py`: add `output_vat_account_id` SelectField (same pattern as existing `input_vat_account_id`)
- `vat_categories/views.py`: populate choices, save on create/update, include in change request data

### `AppSettings`
Register `sv_print_access` with default `'posted_only'`. No migration needed (key-value rows).

---

## Ripple Effects

| Area | Impact |
|---|---|
| VATCategory form/views | Add `output_vat_account_id` field |
| VAT category seeder/fixtures | May need `output_vat_account_id` populated for tests |
| AP Journal | None |
| AR Journal (future) | Will read from `sales_invoices` + `journal_entries`; model changes here are compatible |
| Reports | `SalesInvoice` now has a linked JE — financial reports can use it directly |
| Audit log | All 10 action types covered: create, update, post, cancel, void, export_excel, export_csv, upload_attachment, delete_attachment |
| Tests | `conftest.py` fixtures will need a customer + vat_category with `output_vat_account_id` set |
