# Purchase Bill Detail — Redesign Spec

**Date:** 2026-06-11
**Scope:** `app/purchase_bills/templates/purchase_bills/detail.html`
**Goal:** Make the detail page a faithful read-only mirror of the edit form — same fields, same layout structure, no data hidden when blank.

---

## 1. Layout

The page follows the same two-column structure as the create/edit form.

### Left column — header fields + vendor invoice banner

Fields rendered as label/value pairs (label left, value right), top to bottom:

| Label | Source |
|---|---|
| AP Number | `bill.bill_number` |
| Voucher Date | `bill.bill_date` formatted `%b %d, %Y` |
| Due Date | `bill.due_date` formatted `%b %d, %Y` |
| Payment Terms | `bill.payment_terms` |

Below the field list, a **Vendor Invoice banner** (amber card, always visible):

- Section heading: **Vendor Invoice**
- Left half: sub-label "Invoice #" + value (`bill.vendor_invoice_number` or `— not provided —` when blank), rendered in large monospace bold
- Right half: sub-label "Invoice Date" + value (`bill.vendor_invoice_date` formatted `%b %d, %Y` or `—` when blank)
- Styling: amber background (`#fef9c3`), amber border (`#fde047`), amber text colours (`#92400e` / `#78350f`)

### Right column — vendor card + notes

**Vendor card** (green border, green background):
- Section heading: **Vendor**
- Vendor name (bold, 15px)
- TIN (if present)
- Address (if present)

**Notes** (below vendor card):
- Show when `bill.notes` is non-empty, plain `white-space: pre-wrap`
- Hide when blank (no placeholder needed)

---

## 2. Line Items Table

Columns (in order):

| Column | Content |
|---|---|
| # | `item.line_number` |
| Description | `item.description` |
| Amount (VAT-incl.) | `item.line_total`, right-aligned, monospace |
| VAT | `item.vat_category` + rate, e.g. `VATABLE (12.00%)` |
| WHT | `item.withholding_tax.code` + rate, e.g. `WC010 (10.00%)` or `—` |
| Account Title | `item.account.code ~ ' : ' ~ item.account.name` |

**Removed columns** (were in old detail, no longer shown): Input VAT, WHT Amt.

No section label above the table.

---

## 3. Journal Entry + Bill Summary

Rendered side-by-side below the line items table: JE on the left, Bill Summary on the right (same layout as the form's JE preview | Bill Summary).

### Journal Entry

Section label: **Journal Entry**

Table columns: Code, Account Title, Debit, Credit.

- Debit rows: account title normal weight, left-aligned
- Credit rows: account title **indented 24px**, normal weight (not italic)
- Total row: bold, double top border, showing balanced debit/credit totals

The view function (`purchase_bills.view`) is extended to pass a `je_entries` list to the template — a list of `{account_code, account_name, debit, credit}` dicts:

- **Posted bills:** built from `bill.journal_entry.entries` (already stored in the DB)
- **Draft bills:** computed inline in the view using the same logic as the posting routine — debit each expense account (net of VAT), debit Input VAT account, credit WHT Payable account(s), credit AP Trade account. Account codes for system accounts (Input VAT, WHT Payable, AP Trade) are looked up the same way the post route does.

The template renders `je_entries` regardless of bill status.

### Bill Summary

Section label: **Bill Summary**

Rows in order:

| Row | Value | Notes |
|---|---|---|
| Gross Amount | `bill.subtotal` | |
| Less: Input VAT | `bill.vat_amount` | MANUAL badge if `bill.vat_override` |
| *(thin separator line)* | | |
| Net of VAT | `bill.subtotal - bill.vat_amount` | |
| Add: Input VAT | `bill.vat_amount` | |
| Less: Withholding Tax | `bill.withholding_tax_amount` in red | MANUAL badge if `bill.wt_override` |
| *(thick separator line)* | | |
| Net Amount Payable | `bill.total_amount` | large, bold, blue |

If `bill.amount_paid > 0`, append:
- Amount Paid
- Balance (red if > 0, green if ≤ 0)

---

## 4. What Does Not Change

- Card header (bill number, status badge, overdue badge, action buttons)
- Post / Void / Cancel modals
- Audit trail footer (created by, posted by, voided by, cancelled)
- Badge styles inline `<style>` block
- All existing view logic and route

---

## 5. CSS

No new CSS file needed. The detail template currently uses inline styles throughout and this redesign follows the same pattern. No external stylesheet link is required.

---

## 6. Testing

- Existing smoke and integration tests must still pass
- Manually verify with a bill that has all fields populated (vendor invoice #, date, reference, notes, multiple line items, WHT)
- Manually verify with a bill where vendor invoice # and date are blank — banner shows "— not provided —" and "—"
- Verify JE section renders correctly for both draft (derived) and posted (from journal_entry) bills
