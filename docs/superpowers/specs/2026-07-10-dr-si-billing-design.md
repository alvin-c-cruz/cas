# DR → SI Billing — Design

**Date:** 2026-07-10
**Track:** R-01 (Order-to-Cash) — closes the operational chain SO → DR → **SI (billing)**.
**Status:** design approved (brainstorming); ready for writing-plans.

## Problem

The O2C chain builds a Delivery Receipt against a confirmed SO, but there is no way to
**bill** a delivery into a Sales Invoice. `DeliveryReceipt.sales_invoice_id` + the `billed`
status exist as an inert seam. Today a user must re-key the delivered lines into a new SI by
hand — losing the DR↔SI link, the delivered quantities, and the SO pricing.

## Approach (chosen)

Billing lives **inside the existing SI create form** via a **"Bill delivered DRs" picker**
(option 3 from brainstorming). No new document, no new module.

**No model change.** `DeliveryReceipt.sales_invoice_id` (nullable, already present) is the
DR→SI link and the persistence; the SI carries only a **request-only hidden field**
(`source_dr_ids`) listing the DRs it bills.

### Flow

1. On `/sales-invoices/create`, once a **customer** is selected, a **"Bill delivered DRs"**
   section lists that customer's eligible DRs (see Eligibility). It is additive — the normal
   manual SI still works with no DR pulled.
2. **Pulling a DR appends its delivered lines** as normal, editable SI line items, reusing the
   SI form's existing `addLineItem()`. Each pulled line pre-fills:
   - product = the SO line's product; **qty = the DR line's `delivered_quantity`**
   - **`unit_price` = the SO line's `unit_price`**; `vat_category` / `vat_rate` = the SO line's
   - **`account_id` = `Product.default_account_id`** (revenue); null if the product has none —
     the user fills it before posting (SI already guards "every line needs a revenue account").
   - WHT is resolved from the **customer**, exactly as a manual SI line does today.
   - The DR's id is added to the hidden `source_dr_ids` set.
3. Lines stay **fully editable** (price/qty/account adjustable) — the SI is a real document.
4. On **SI create** (draft): for each id in `source_dr_ids`, set `dr.sales_invoice_id = si.id`
   and `dr.status = 'billed'`.
5. On **SI void / cancel**: every DR with `sales_invoice_id == si.id` reverts to
   `status='delivered'`, `sales_invoice_id=None`.

### Configurable consolidation (company setting)

New setting **`si_dr_billing_consolidate`** (`'1'`/`'0'`, **default `'0'` = OFF**), set on the
Company Settings page like the other toggles:

- **OFF (default):** one DR per SI. After one DR is pulled the picker locks; the SI-create view
  server-guards `len(source_dr_ids) <= 1` (raises a clear error otherwise).
- **ON:** many delivered DRs → one consolidated SI.

Only the picker's "add another DR" affordance and one server-side guard depend on this flag.

### Eligibility (picker query)

A DR is billable when: `branch_id == session branch` AND `customer_id == the SI's customer`
AND `status == 'delivered'` AND `sales_invoice_id IS NULL`. Because a billed/linked DR has a
non-null `sales_invoice_id`, **double-billing is structurally impossible**.

### New endpoint

`GET /sales-invoices/billable-drs?customer_id=<id>` → JSON:
```json
{ "consolidate": false,
  "drs": [ { "id": 12, "dr_number": "DR-…", "delivery_date": "…",
             "lines": [ { "product_id": 3, "product_code": "P001", "product_name": "…",
                          "quantity": 10.0, "unit_price": 100.0, "uom_display": "PC",
                          "vat_category": "V12", "vat_rate": 12.0, "account_id": 41 } ] } ] }
```
Prices/VAT come from each DR line's `sales_order_item`; `account_id` from the product default.
`consolidate` echoes the setting so the JS knows whether to lock after one pull.

## Boundaries (deliberately out of scope)

- **Whole-DR billing only** — pulling a DR bills all its delivered lines; if the user deletes a
  pulled line the DR is still marked billed. No partial-DR billing.
- Same product across DRs stays **separate SI lines** (traceability), not merged.
- **No model change** (DR/SI schema untouched; `source_dr_ids` is request-only).
- No re-open of a billed DR except via SI void/cancel.
- COGS / `post_delivery_je` (R-03) is unaffected and remains inert.

## Components / files

- `app/sales_invoices/views.py` — `billable_drs` endpoint; parse `source_dr_ids` on create;
  bill/unbill helpers hooked into create + void + cancel; consolidate-guard.
- `app/sales_invoices/templates/sales_invoices/form.html` — the picker UI + hidden
  `source_dr_ids`; a new `si_dr_billing.js` (or an addition to the form JS) that fetches
  `billable-drs`, and on pull calls `addLineItem()` per DR line + toggles the picker per the
  `consolidate` flag.
- `app/company_settings/{forms,views}.py` + template — the `si_dr_billing_consolidate` toggle.
- `app/delivery_receipts/` — no change (the `sales_invoice_id`/`billed` seam already exists);
  the DR detail may optionally show "Billed on SI-…" (read-only link).

## Error handling

- Consolidate OFF + more than one DR pulled → SI create raises `ValueError` ("Consolidated
  billing is off — bill one Delivery Receipt per invoice."), re-renders the form.
- A `source_dr_ids` entry that is not eligible at create time (race: billed/deleted meanwhile)
  → skip it with a flash, or raise — **raise** (fail-closed; the user re-pulls).
- SI post still enforces the per-line revenue-account guard (unchanged).

## Testing (TDD)

- `billable_drs` filters by customer/branch/status/unlinked; returns priced lines.
- Pulling pre-fills SI lines (qty=delivered, price=SO line, account=product default).
- SI create with `source_dr_ids` sets each DR `billed` + `sales_invoice_id`.
- SI void/cancel reverts the DRs to `delivered` + unlinks.
- Billed DRs are excluded from a later picker (no double-bill).
- Consolidate OFF: second DR rejected at create; ON: both billed.
- e2e smoke: select customer → pull a delivered DR → its lines populate → save → DR shows billed.
```
