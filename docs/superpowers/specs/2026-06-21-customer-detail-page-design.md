# Customer Detail Page — Design Spec

**Date:** 2026-06-21
**Status:** Approved (brainstorm) — pending implementation plan
**Author:** alvin-c-cruz (with Claude)

## Goal

Give Customers a detail page that mirrors the Vendor detail page
(`/vendors/<id>`, `app/vendors/templates/vendors/detail.html`). Customers
currently have no detail view at all — list rows link to **Edit**, and
`/customers/<id>` is undefined. This brings Customers to parity with Vendors
(per the standing Customers↔Vendors parity-mirror convention).

The Vendor page the user likes has:
- A header (code + Active/Inactive badge + role-gated Edit button)
- A two-tab bar: **Overview** and **Bills (N)**
- Overview = Vendor Info card + AP Aging card + WHT Withheld YTD card
- Bills = filterable (date range + status), paginated invoice table

## Decisions (from brainstorm)

1. **Third overview panel = "Creditable WHT (BIR 2307) YTD".** The accounting
   flips on the AR side: `SalesInvoice.withholding_tax_amount` is tax the
   *customer* withholds from us (creditable WHT, BIR 2307 we *receive*), not tax
   we withhold. The calculation is identical to the vendor's `compute_wht_ytd`;
   only the label/meaning changes.
2. **Customer list code/name links re-point to the new detail page** (full
   mirror of vendors). The row Edit button stays.

## Architecture & Routing

New view `customers.detail` at `GET /customers/<int:id>`, mirroring
`vendors.detail` (`app/vendors/views.py:76-128`):

- `?tab=overview` (default) → Customer Info + AR Aging + Creditable WHT YTD.
- `?tab=invoices` → filterable (`date_from`, `date_to`, `status`), paginated
  (20/page) list of that customer's Sales Invoices, `order_by(invoice_date.desc())`.
- Access: `@login_required` only — matches `vendors.detail`, which is **not**
  role-gated for read. Per-module access for staff is already enforced globally
  via the registry/`before_request`; no inline role gate is added. Reads are not
  audited (matches vendors — no `log_audit` call).
- `total_invoices = SalesInvoice.query.filter_by(customer_id=id).count()` for the
  tab badge.

Single template: `app/customers/templates/customers/detail.html`, structured
identically to `vendors/detail.html`. CSS classes renamed `vendor-*` →
`customer-*` (tab bar, overview grid, info table) within the template's inline
`<style>` block (mirrors how the vendor template scopes its own styles). Use the
literal `₱` glyph (never `&#8369;`). Status-badge mapping reused verbatim
(`partially_paid → partial`, `voided → void`).

## Data Helpers — new `app/customers/utils.py`

Mirror of `app/vendors/utils.py`:

### `compute_ar_aging(customer_id)`
Same bucket logic as `compute_ap_aging`, over `SalesInvoice` where
`status in ('posted', 'partially_paid')`, using `balance` and `due_date`,
`today = ph_now().date()`:

- `current` — `days_overdue <= 0`
- `1_30`, `31_60`, `61_90`, `90_plus`
- `total` — sum of buckets

Skips invoices with `due_date is None`. Amount = `invoice.balance or Decimal('0.00')`.
Returns a dict of `Decimal`.

### `compute_creditable_wht_ytd(customer_id)`
Same group-by-`wt_id` sum as `compute_wht_ytd`, over `SalesInvoiceItem.wt_amount`
joined to `SalesInvoice` where `status == 'posted'` and
`extract('year', invoice_date) == ph_now().year` and `wt_id` is not null.
Returns `[{code, name, total}]` (only WT codes that still resolve).

(`generate_next_customer_code`, `populate_dropdown_choices` already live in
`customers/views.py` — not moved, not touched.)

## Overview Tab Content

**Customer Information** card — table rows: Code (bold), Name, TIN, Contact,
Phone, Email, Address, Postal Code, Payment Terms, Default VAT (badge or `—`),
Default WHT (badges from `customer.withholding_taxes` or `—`).
*Field difference from vendor:* Customer has **no `check_payee_name`**, so that
row is dropped. Every other Info row maps 1:1.

**AR Aging (Posted Invoices)** card — five buckets + Total Outstanding row;
`90_plus` shown in `var(--red)`; all amounts `₱{{ '{:,.2f}'.format(...) }}`.

**Creditable WHT (BIR 2307) YTD** card — one row per WT code (`{{ code }} — {{ name }}`,
amount right-aligned), or italic empty-state "No creditable WHT recorded this
calendar year."

## Invoices Tab

Filter form (GET, mirrors Bills tab): hidden `tab=invoices`, `date_from`,
`date_to`, `status` select (all / draft / posted / partially_paid / paid /
voided / cancelled), Filter + Clear buttons.

Table columns: **Invoice #** (links to `sales_invoices.view`), **Invoice Date**,
**Due Date**, **Subtotal**, **Output VAT** (`vat_amount`), **WHT**
(`withholding_tax_amount`, shown as `-₱…` in red when > 0, else `—`),
**Net Amount** (`total_amount`, bold), **Status** (badge).

Pagination identical to vendors: prev/next buttons carrying `tab`, `page`,
`date_from`, `date_to`, `status`; "Page X of Y (N invoices)" caption; shown only
when `pagination.pages > 1`. Empty-state row spanning all columns.

## List Links

In `app/customers/templates/customers/list.html`, re-point the code link
(line ~50) and name link (line ~52) from `customers.edit` → `customers.detail`.
Keep the `customer-link` class and the row's Edit action button unchanged.

## Ripple / Blast Radius

- **Models:** none changed. **Migration:** none.
- **Exports / numbering / SI views:** untouched.
- **base.html / nav:** untouched (Customers nav already points at the list).
- **Access:** confirm `customers.detail` is reachable as a read view for each
  role under the per-module access registry; no new registry entry needed beyond
  what already gates `customers.*`.
- **Cache-buster:** the detail template uses an inline `<style>` block (no shared
  static file), so no `?v=N` bump is required. If any shared CSS is touched
  instead, bump every linking template.

## Testing (TDD — write tests first)

- `compute_ar_aging`: bucket boundaries (0, 30, 60, 90, 91 days), `None` due_date
  skipped, only posted/partially_paid counted, total = sum.
- `compute_creditable_wht_ytd`: grouping by wt_id, YTD-year filter, posted-only,
  null wt_id excluded, unresolved wt_id dropped.
- `detail` route: 200 for admin/accountant/staff/viewer (read access); overview
  vs invoices tab rendering; tab badge count.
- Invoices tab: date/status filter narrows results; pagination math.
- List links: code/name `href` now targets `customers.detail` not `customers.edit`.
- Per parity-mirror + audit conventions: no audit assertion needed (read view,
  matching vendors).

## Non-Goals

- No customer-side payment/CRV history beyond the Sales Invoices tab.
- No model fields, no migration, no export changes.
- No changes to the Vendor detail page.
