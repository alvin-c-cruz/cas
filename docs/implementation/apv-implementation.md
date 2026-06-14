# AP Voucher (Purchase Bills) — Implementation Reference

## Overview

The AP Voucher module records supplier invoices in the AP sub-ledger. Every saved bill
automatically generates a matching `JournalEntry` of type `purchase`; posting the bill
promotes that entry to `posted` so the amounts enter the GL.

Blueprint: `purchase_bills_bp` registered at `/purchase-bills`  
Source files:
- `app/purchase_bills/models.py` — `PurchaseBill`, `PurchaseBillItem`, `PurchaseBillAttachment`
- `app/purchase_bills/views.py` — all routes, JE builder, helpers
- `app/purchase_bills/utils.py` — `compute_bills_summary`
- `app/purchase_bills/forms.py` — `PurchaseBillForm`

---

## Data Model

### `PurchaseBill` (table `purchase_bills`)

| Column | Type | Notes |
|---|---|---|
| `id` | Integer PK | |
| `branch_id` | FK → `branches` | All operations are branch-scoped |
| `bill_number` | String(50) unique | `AP-YYYY-MM-NNNN`, sequential per month |
| `bill_date` | Date | Period-validation checked on save |
| `due_date` | Date | |
| `vendor_id` | FK → `vendors` | |
| `vendor_name/tin/address` | String | Snapshot at creation time — survives vendor edits |
| `vendor_invoice_number` | String(100) | Required to post when VAT or WHT is non-zero |
| `vendor_invoice_date` | Date | Required to post when VAT or WHT is non-zero |
| `payment_terms` | String(50) | e.g. `Net 30` |
| `notes` | Text | Required, maps to "Particulars" in the AP Journal |
| `subtotal` | Numeric(15,2) | Sum of VAT-inclusive line amounts |
| `vat_amount` | Numeric(15,2) | Extracted input VAT; overridable |
| `total_before_wt` | Numeric(15,2) | Equals `subtotal` (VAT is extracted, not added) |
| `withholding_tax_rate` | Numeric(5,2) | Stored but derived from line items |
| `withholding_tax_amount` | Numeric(15,2) | Sum of per-line WHT; overridable |
| `vat_override / wt_override` | Boolean | True when the amount was manually set |
| `total_amount` | Numeric(15,2) | `subtotal − withholding_tax_amount` |
| `amount_paid` | Numeric(15,2) | Updated by payment processing |
| `balance` | Numeric(15,2) | `total_amount − amount_paid` |
| `journal_entry_id` | FK → `journal_entries` | Auto-created on first save |
| `status` | String(20) | See lifecycle below |
| `created_by_id / posted_by_id / voided_by_id` | FK → `users` | |
| `created_at / updated_at / posted_at / cancelled_at / voided_at` | DateTime | PHT |
| `void_reason / cancel_reason` | String | Min 10 chars enforced in views |

### `PurchaseBillItem` (table `purchase_bill_items`)

Each line holds a VAT-inclusive `amount`. The `calculate_amounts()` method extracts VAT
and computes WHT on the net base (BIR EWT standard):

```
net_base  = amount / (1 + vat_rate/100)   # or amount when vat_rate = 0
vat_amount = amount − net_base
wt_amount  = net_base × wt_rate / 100
line_total = amount                         # equals the VAT-inclusive input amount
```

| Column | Notes |
|---|---|
| `bill_id` | FK parent |
| `line_number` | 1-based, ordered display |
| `description` | Required |
| `amount` | VAT-inclusive input |
| `vat_category` | Code string; rate snapshot in `vat_rate` |
| `vat_rate` | Snapshot of `VATCategory.rate` at creation time |
| `vat_amount` | Extracted at save |
| `line_total` | Equals `amount` |
| `account_id` | FK → `accounts` (expense/asset) |
| `wt_id` | FK → `withholding_tax`; rate snapshot in `wt_rate` |
| `wt_rate` | Snapshot of `WithholdingTax.rate` |
| `wt_amount` | Computed at save |

### `PurchaseBillAttachment` (table `purchase_bill_attachments`)

Stored at `instance/uploads/purchase_bills/<bill_id>/<uuid4-hex>.<ext>`.  
Images (`image/*` MIME) can be previewed; SVG is excluded (XSS risk).  
Upload locked to `draft` status; delete locked to `draft` + accountant/admin.  
Files are deleted from disk on bill void.

---

## Bill Number Generation

```
AP-YYYY-MM-NNNN   e.g. AP-2026-06-0001
```

`generate_bill_number()` queries the highest bill number with the current `AP-YYYY-MM-`
prefix and increments. Resets to `0001` each calendar month. Voided bills keep their
number (unique constraint; the sequence counts all bills including voided).

---

## Status Lifecycle

```
draft  →  posted  →  partially_paid  →  paid
  │              ↘
  └─ voided       cancelled
```

- **draft → posted**: `post` route (accountant/admin). Promotes the linked draft JE to `posted`.
  Requires `vendor_invoice_number` and `vendor_invoice_date` when VAT or WHT is non-zero.
- **posted → cancelled**: `cancel` route (accountant/admin). Creates a full reversal JE
  (`entry_type='reversal'`, `is_reversing=True`). Requires cancel reason (≥10 chars) and
  reversal date. Blocked if `amount_paid > 0`.
- **draft → voided**: `void` route (staff+). No reversal JE needed — the draft JE is
  deleted. Requires void reason (≥10 chars). Attachments deleted from disk.

---

## Journal Entry Construction

Performed by `_post_bill_je(bill, user_id)` in `views.py`.

**Entry type:** `purchase`  
**Status:** mirrors the bill — `draft` while bill is draft, `posted` when bill is posted.

Debit lines (in order):
1. One line per `PurchaseBillItem` that has an `account_id`: amount = `line_total − vat_amount` (net base)
2. One line per input-VAT bucket (grouped by `VATCategory.input_vat_account`): amount from `_input_vat_buckets(bill)`

Credit lines:
3. WHT Payable (account `20301`) for `withholding_tax_amount`, if non-zero
4. Accounts Payable — Trade (account `20101`) for `total_amount`

**Rounding residual:** Any debit/credit imbalance (from VAT extraction rounding or a manual
VAT override) is absorbed into the first expense line's debit amount so the JE always
balances exactly.

**VAT override handling (`_input_vat_buckets`):** When `bill.vat_override` is True,
`bill.vat_amount` differs from the computed sum. The difference is applied to the largest
VAT bucket. Raises `ValueError` if any bucket would go negative.

**Reversal JE (`_create_reversal_je`):** Swaps every debit/credit from the source JE.
Used for both `cancel` and any future void-of-posted flows.

---

## View Access Control

| Route | Minimum role |
|---|---|
| List, view, export | `login_required` (all authenticated users) |
| Create, edit, upload/delete attachments | `staff_or_above` (staff, accountant, admin) |
| Post, cancel, delete attachment | `accountant_or_admin` |
| Void | `staff_or_above` |

All routes require a `selected_branch_id` in session (`before_request` guard redirects
to branch-select if missing).

---

## List & Filters

`_filtered_bills_query()` applies branch scope plus optional:
- `status`: one of the six valid statuses or `all`
- `vendor`: `vendor_id` integer or `all`
- `q`: ILIKE on `bill_number` or `vendor_name`
- `date_from / date_to`: filter on `bill_date`
- `ids`: comma-separated list of IDs (exports only; overrides all other filters)

Paginated at 50 per page. Summary metrics (`compute_bills_summary`) show outstanding,
overdue, due-soon (within 7 days), and draft counts for the page header cards.

---

## Exports

Both Excel and CSV use `_EXPORT_COLUMNS` / `_EXPORT_HEADERS` (13 columns including
financial totals). Exports honour all active list filters. The audit log records
`export_excel` / `export_csv` with filter context.

---

## Print Preview

Route: `GET /purchase-bills/<id>/print`  
Template: `purchase_bills/print.html`  
Access: `apv_print_access` setting — `posted_only` (default) or `all`.

JE lines are sorted: non-VAT debits → VAT debits → credits, each sub-group by account
code. Company name, address, and TIN are pulled from `AppSettings`.

---

## Audit Log Events

| Action | Trigger |
|---|---|
| `create` | Bill saved (create route) |
| `update` | Bill edited (edit route) |
| `post` | Bill status changed to `posted` |
| `cancel` | Bill cancelled with reversal |
| `void` | Draft bill voided |
| `export_excel` / `export_csv` | Export routes |
| `create` (module `purchase_bill_attachment`) | File uploaded |
| `delete` (module `purchase_bill_attachment`) | File deleted |

---

## Key Invariants

- `notes` is required — it becomes the "Particulars" column in the AP Journal.
- Every saved bill (including drafts) has a linked JE; the JE is recreated on edit.
- A bill's vendor snapshot fields (`vendor_name`, `vendor_tin`, `vendor_address`) are
  frozen at creation and never updated from the vendor record afterward.
- VAT extraction, not VAT addition: `subtotal` is always the VAT-inclusive line sum.
- WHT is computed on the net base (before-VAT amount) per BIR EWT rules.
- Period validation (`validate_transaction_date_with_flash`) runs on create and edit to
  block posting into closed periods.
