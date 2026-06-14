# APV Print Preview — Design Spec

**Date:** 2026-06-14  
**Status:** Approved

---

## Problem

The APV detail page has no print capability. Accountants need to print a clean, BIR-compliant Accounts Payable Voucher to attach to supporting documents and obtain wet-ink signatures. The current detail page includes navigation, sidebar, and UI chrome that is not suitable for printing.

---

## Solution

Three additions:

1. A standalone print preview page at `/purchase-bills/<id>/print` — no sidebar, no navbar, A4 portrait.
2. A "Print" button on the APV detail page action bar, whose visibility is controlled by an app setting.
3. A new app setting `apv_print_access` that controls whether drafts or only posted vouchers can be printed.

---

## Print Preview Page

### Route

```
GET /purchase-bills/<id>/print
```

- Requires login (`@login_required`). No role restriction — any authenticated user can print.
- Returns 404 if the bill does not belong to the current session branch.
- Template extends nothing (standalone page, no base.html).

### Template: `app/purchase_bills/templates/purchase_bills/print.html`

Full-page print template with `@media print { @page { size: A4 portrait; margin: 15mm; } }` and a "Print / Close" button visible only on screen (hidden in print CSS).

### Layout (top to bottom)

1. **Company header** — company name (bold, large), address + TIN (from `AppSettings`), "ACCOUNTS PAYABLE VOUCHER" title
2. **Two-column info row**
   - Left: APV No., Date, Due Date, Payment Terms
   - Right: Vendor block (name, TIN, Invoice No., Invoice Date)
3. **Particulars table** — columns: #, Description/Particulars, Amount, Account Title
4. **Side-by-side row**
   - Left (flex:1): Journal Entry table — Code, Account Title, Debit, Credit; totals row at bottom
   - Right (flex:0 0 200px): Summary box — Gross Amount → Less: Input VAT → (rule) → Net of VAT → Add: Input VAT → Less: Withholding Tax → (double rule) → **Net Amount Payable** (bold, blue)
5. **Notes** — full-width below the JE + Summary row; yellow background; shown only if `bill.notes` is non-empty
6. **Signature block** — three equal boxes: PREPARED BY / REVIEWED BY / APPROVED BY; each has a blank line for name + date
7. **Audit footer** — "Posted by: X · [date] | Printed: [PH datetime]"; hidden if bill is draft

### Journal Entry Line Ordering

Lines from `bill.journal_entry.lines.all()`, sorted:
1. Debit lines where account is **not** an Input VAT account — sorted by `account.code` ascending
2. Debit lines where account **is** an Input VAT account — sorted by `account.code` ascending
3. Credit lines — sorted by `account.code` ascending

Input VAT accounts are identified by collecting `{c.input_vat_account_id for c in VATCategory.query.all() if c.input_vat_account_id}`.

Credit column shows positive values (no parentheses).

### Page Overflow

Natural CSS flow — content extends across as many A4 pages as needed. No special pagination logic. `page-break-inside: avoid` is NOT applied to signatures; they flow naturally with the rest of the content.

---

## Print Button on APV Detail Page

A "Print" button added to the action bar in `app/purchase_bills/templates/purchase_bills/detail.html`. It opens `/purchase-bills/<id>/print` in a new tab (`target="_blank"`).

**Visibility logic** (controlled by `apv_print_access` setting read in the view):

| Setting value | Button shown when |
|---|---|
| `posted_only` (default) | `bill.status in ('posted', 'partially_paid', 'paid')` |
| `draft_and_posted` | `bill.status not in ('voided', 'cancelled')` |

The view passes `apv_print_access` as a template variable. The button is rendered conditionally in the template.

---

## App Setting: `apv_print_access`

**Key:** `apv_print_access`  
**Values:** `'posted_only'` | `'draft_and_posted'`  
**Default:** `'posted_only'` (read via `AppSettings.get_setting('apv_print_access', 'posted_only')`)

Added to:
- `app/company_settings/forms.py` — new `SelectField` on `CompanySettingsForm`
- `app/company_settings/views.py` — added to `SETTINGS_KEYS` list
- `app/company_settings/templates/company_settings/form.html` — new "Documents" section card after the "Accounting" section, before the Save button

---

## No Server Changes to Existing Routes

The existing `/purchase-bills/<id>` view is unchanged except for passing `apv_print_access` to the template. No model changes. No migrations.

---

## Testing

- Setting: save `draft_and_posted`, reload page, assert it persists; save `posted_only`, assert it persists.
- Print route: GET `/purchase-bills/<id>/print` as logged-in user returns 200 and contains the bill number.
- Print route: GET with wrong branch session returns 404.
- Button visibility: detail page with `posted_only` setting and draft bill — no print button; with `draft_and_posted` — print button present.
