# Cash Disbursement Voucher (CDV) — Design Spec

**Date:** 2026-06-14  
**Status:** Approved  
**Phase:** 1 of 2 — CDV module. CDJ (columnar journal) is a separate spec after this is shipped.

---

## Overview

The Cash Disbursement Voucher records cash payments made by the business. A single CDV can:
1. Pay one or more open APV bills (reduces the AP sub-ledger balance)
2. Record direct expense payments (like an APV but paying immediately from cash)
3. Do both in the same voucher

CDV is modelled directly after APV — same blueprint structure, same JE lifecycle, same
access-control decorators. The key differences are the cash/bank account on the credit
side, the AP application section, and the side-effect of updating APV bill balances on
post/cancel.

---

## Document Numbering

```
CD-YYYY-MM-NNNN   e.g. CD-2026-06-0001
```

Sequential per month within the branch (same algorithm as APV's `generate_bill_number`).
Voided CDVs keep their number.

---

## Data Model

### `CashDisbursementVoucher` (table `cash_disbursement_vouchers`)

| Column | Type | Notes |
|---|---|---|
| `id` | Integer PK | |
| `branch_id` | FK → `branches` | Required, branch-scoped |
| `cdv_number` | String(50) unique | `CD-YYYY-MM-NNNN` |
| `cdv_date` | Date | Period-validated on save |
| `vendor_id` | FK → `vendors` | Payee; required |
| `vendor_name` | String(200) | Snapshot |
| `vendor_tin` | String(20) | Snapshot |
| `payment_method` | String(20) | `cash`, `check`, `bank_transfer`, `online` |
| `check_number` | String(50) | Populated when `payment_method = 'check'` |
| `check_date` | Date | Populated when `payment_method = 'check'` |
| `check_bank` | String(100) | Populated when `payment_method = 'check'` |
| `cash_account_id` | FK → `accounts` | The Cash/Bank account being credited |
| `notes` | Text | Required — maps to "Particulars" in CDJ |
| `total_ap_applied` | Numeric(15,2) | Sum of `CDVApLine.amount_applied` |
| `total_expense` | Numeric(15,2) | Sum of `CDVExpenseLine.line_total` (VAT-inclusive) |
| `total_vat` | Numeric(15,2) | Sum of `CDVExpenseLine.vat_amount` |
| `total_wt` | Numeric(15,2) | Sum of `CDVExpenseLine.wt_amount` |
| `total_amount` | Numeric(15,2) | `total_ap_applied + total_expense − total_wt` (actual cash out) |
| `vat_override` | Boolean | True when `total_vat` was manually set |
| `wt_override` | Boolean | True when `total_wt` was manually set |
| `status` | String(20) | `draft`, `posted`, `voided`, `cancelled` |
| `journal_entry_id` | FK → `journal_entries` | Auto-created on save; draft while CDV is draft |
| `created_by_id` | FK → `users` | |
| `posted_by_id` | FK → `users` | |
| `voided_by_id` | FK → `users` | |
| `void_reason` | String(255) | Min 10 chars |
| `cancel_reason` | String(500) | Min 10 chars |
| `created_at / updated_at / posted_at / voided_at / cancelled_at` | DateTime | PHT |

### `CDVApLine` (table `cdv_ap_lines`)

One row per APV bill being paid.

| Column | Type | Notes |
|---|---|---|
| `id` | Integer PK | |
| `cdv_id` | FK → `cash_disbursement_vouchers` | |
| `line_number` | Integer | 1-based |
| `bill_id` | FK → `purchase_bills` | |
| `bill_number` | String(50) | Snapshot |
| `original_balance` | Numeric(15,2) | Snapshot of `bill.balance` when the line is added |
| `amount_applied` | Numeric(15,2) | ≤ `original_balance`; user-editable |

### `CDVExpenseLine` (table `cdv_expense_lines`)

Identical in structure and calculation to `PurchaseBillItem`.

| Column | Type | Notes |
|---|---|---|
| `id` | Integer PK | |
| `cdv_id` | FK → `cash_disbursement_vouchers` | |
| `line_number` | Integer | 1-based |
| `description` | String(500) | Required |
| `amount` | Numeric(15,2) | VAT-inclusive |
| `vat_category` | String(100) | Code string |
| `vat_rate` | Numeric(5,2) | Snapshot |
| `line_total` | Numeric(15,2) | Equals `amount` |
| `vat_amount` | Numeric(15,2) | Extracted; `amount − net_base` |
| `account_id` | FK → `accounts` | Expense / asset account |
| `wt_id` | FK → `withholding_tax` | Optional |
| `wt_rate` | Numeric(5,2) | Snapshot |
| `wt_amount` | Numeric(15,2) | `net_base × wt_rate / 100` |

`calculate_amounts()` follows the APV formula exactly:
```
net_base  = amount / (1 + vat_rate/100)
vat_amount = amount − net_base
wt_amount  = net_base × wt_rate / 100
line_total = amount
```

---

## Status Lifecycle

```
draft  →  posted
  │          ↘
  └─ voided   cancelled
```

- **draft → voided**: CDV was never posted. Delete the draft JE. Requires void reason ≥ 10 chars. No APV balance change.
- **draft → posted**: Promote draft JE to posted. Update each referenced APV bill (see below).
- **posted → cancelled**: Create reversal JE. Reverse each referenced APV bill's balance. Requires cancel reason ≥ 10 chars. Blocked if any referenced APV is already fully paid by another CDV (guard: `bill.amount_paid < amount_applied` after reversal would go negative).

No `partially_paid` / `paid` states on CDV itself — those statuses live on the APV bills.

---

## Journal Entry Construction

**Entry type:** `disbursement`  
**Status:** `draft` while CDV is draft; `posted` on CDV post.  
**Reference:** `cdv_number`  
**Description:** `CD {cdv_number} — {vendor_name}`

### Debit lines (in order)

1. **Per CDVApLine:** Dr `Accounts Payable — Trade (20101)`, amount = `amount_applied`
2. **Per CDVExpenseLine with account:** Dr expense account, amount = `line_total − vat_amount` (net base)
3. **Per CDVExpenseLine VAT bucket** (grouped by `VATCategory.input_vat_account`, same `_input_vat_buckets` logic as APV): Dr input VAT account, amount = bucket sum

### Credit lines

4. **Per CDVExpenseLine WHT:** Cr `WHT Payable — Expanded (20301)`, amount = `wt_amount` (if non-zero)
5. **Cash/Bank account (`cash_account_id`):** Cr `total_amount`

### Balance verification

```
total_debits  = total_ap_applied + sum(expense net bases) + sum(expense VAT amounts)
              = total_ap_applied + total_expense   [net+vat = line_total]

total_credits = total_wt + total_amount
              = total_wt + (total_ap_applied + total_expense − total_wt)
              = total_ap_applied + total_expense  ✓
```

Rounding residual absorbed into the first expense debit line (same pattern as APV). AP-only CDVs carry no rounding residual because `amount_applied` values are exact user inputs with no VAT extraction.

---

## APV Balance Update on Post

For each `CDVApLine`:
```python
bill.amount_paid += line.amount_applied
bill.balance     -= line.amount_applied
if bill.balance <= 0:
    bill.status = 'paid'
elif bill.amount_paid > 0:
    bill.status = 'partially_paid'
```

All updates committed atomically with the JE post.

## APV Balance Reversal on Cancel

For each `CDVApLine`:
```python
bill.amount_paid -= line.amount_applied
bill.balance     += line.amount_applied
if bill.amount_paid <= 0:
    bill.status = 'posted'
else:
    bill.status = 'partially_paid'
```

Guard: if `bill.amount_paid − line.amount_applied < 0` for any line, reject the cancel
with a flash error explaining which bill is inconsistent.

Reversal JE: same `_create_reversal_je` pattern as APV cancel — swaps all debits and
credits from the original CDV JE.

---

## Form Layout

The CDV form mirrors the APV form layout:

**Left column (header fields):**
- CDV Number (auto-generated, editable)
- CDV Date
- Vendor (Choices.js search-select, same as APV)
- Payment Method (native select)
- Check Number / Check Date / Check Bank (shown when method = check)
- Cash/Bank Account (Choices.js account picker)
- Notes (required)

**Right column (two sections):**

**Section A — Pay AP Bills** (collapsible or always visible)
- Table of open APV bills for the selected vendor: columns = AP No., Vendor Invoice #, Bill Date, Balance, Amount to Pay
- Amount auto-fills to `bill.balance`; user can reduce it but not exceed it
- "Open bills" = APV bills for the selected vendor, current branch, status in (`posted`, `partially_paid`), `balance > 0`
- Add/remove rows by selecting from a filtered list of open bills

**Section B — Direct Expenses** (same table as APV line items)
- Description, Amount, VAT Category, Account, WHT — identical to APV line items table
- Add Row / Remove Row buttons

**Bill Summary panel** (right side, same as APV):
- AP Applied, Direct Expenses subtotal, Input VAT, WHT Deducted, **Net Cash Disbursed** (= total_amount)
- VAT and WHT pencil-override buttons (expense section only)

---

## Routes

| Method | URL | Handler | Notes |
|---|---|---|---|
| GET | `/cash-disbursements` | `list_cdvs` | List with summary cards, filters |
| GET | `/cash-disbursements/create` | `create` | Form |
| POST | `/cash-disbursements/create` | `create` | Save draft + JE |
| GET | `/cash-disbursements/<id>` | `view` | Detail with JE preview |
| GET | `/cash-disbursements/<id>/edit` | `edit` | Draft only |
| POST | `/cash-disbursements/<id>/edit` | `edit` | Recreate JE |
| POST | `/cash-disbursements/<id>/post` | `post` | Post JE + update APV balances |
| POST | `/cash-disbursements/<id>/void` | `void` | Draft only; delete JE |
| POST | `/cash-disbursements/<id>/cancel` | `cancel` | Posted only; reversal JE + reverse APV balances |
| GET | `/cash-disbursements/<id>/print` | `print_cdv` | Print preview |
| GET | `/cash-disbursements/export/excel` | `export_excel` | Filtered export |
| GET | `/cash-disbursements/export/csv` | `export_csv` | Filtered export |

---

## Access Control

Mirrors APV exactly:

| Action | Minimum role |
|---|---|
| List, view, export | `login_required` |
| Create, edit | `staff_or_above` |
| Post, cancel | `accountant_or_admin` |
| Void | `staff_or_above` |

Branch guard: `before_request` redirects to branch-select if no `selected_branch_id`.

---

## Audit Trail

| Action | Trigger |
|---|---|
| `create` | CDV saved |
| `update` | CDV edited |
| `post` | CDV posted |
| `void` | Draft CDV voided |
| `cancel` | Posted CDV cancelled |
| `export_excel` / `export_csv` | Export routes |

---

## List & Filters

Same pattern as APV list:
- `status`: all / draft / posted / voided / cancelled
- `vendor`: vendor_id or all (Choices.js search-select)
- `q`: ILIKE on `cdv_number` or `vendor_name`
- `date_from / date_to`: filter on `cdv_date`
- `payment_method`: all / cash / check / bank_transfer / online

Summary cards: Total Disbursed (posted, current month), Draft count, Cancelled count.

---

## Print Preview

Same pattern as APV print:
- JE lines sorted: non-VAT debits → VAT debits → credits, by account code
- Company name, address, TIN from `AppSettings`
- Check details shown when `payment_method = 'check'`
- AP applications listed as a separate section above expense lines

---

## Testing Notes

- Verify JE balances for: AP-only CDV, expense-only CDV, mixed CDV, CDV with VAT override, CDV with WHT
- Verify APV bill status transitions: posted → partially_paid → paid
- Verify cancel reverses APV balances correctly
- Verify audit log on each action
- Verify branch scope (bills from other branches must not appear in AP picker)
- Verify amount_applied cannot exceed original_balance at save time

---

## Out of Scope (This Spec)

- CDJ (Cash Disbursements Journal) — separate spec, built after CDV ships
- Attachments — can be added later; not in initial scope
- Partial VAT override on AP lines — AP lines always use the exact `amount_applied`; no VAT at payment time
