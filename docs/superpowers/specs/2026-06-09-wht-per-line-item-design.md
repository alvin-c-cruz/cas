# WHT Per Line Item — Purchase Bills

**Date:** 2026-06-09
**Scope:** `app/purchase_bills/`, `app/vendors/`
**Approach:** Move withholding tax from bill-level to line-item level, vendor-driven

---

## Problem

`PurchaseBill` applies a single `withholding_tax_rate` to the entire bill's subtotal. This is wrong when a bill has line items subject to different WHT codes (e.g., professional fees at 10% on one line, contractor payment at 2% on another). Each line item needs its own WHT selection, driven by the vendor's configured WHT codes.

---

## Model Changes

### `PurchaseBillItem` — new fields

| Field | Type | Nullable | Default | Purpose |
|---|---|---|---|---|
| `wt_id` | FK → withholding_tax | Yes | None | Selected WHT code for this line |
| `wt_rate` | Decimal(5,2) | Yes | None | Snapshot of rate at bill creation time |
| `wt_amount` | Decimal(15,2) | No | 0.00 | `line_total × wt_rate / 100` |

### `PurchaseBill` — changes

- `withholding_tax_rate` — DB column retained (non-destructive; existing data preserved). Removed from form and no longer used as input. Set to `0.00` on create and edit saves.
- `withholding_tax_amount` — retained. Now computed as `SUM(item.wt_amount for item in line_items)` instead of `subtotal × rate / 100`.
- `calculate_totals()` — replace `self.withholding_tax_amount = self.subtotal * rate / 100` with `self.withholding_tax_amount = sum(item.wt_amount for item in self.line_items)`.

### Migration

Additive only — three nullable columns on `purchase_bill_items`. Safe for existing data. No backfill required (existing items remain with `wt_id=None`, `wt_amount=0`).

---

## API Endpoint

```
GET /vendors/<int:id>/defaults
@login_required
```

Response:

```json
{
  "withholding_taxes": [
    {"id": 3, "code": "WC010", "name": "Professional Fees", "rate": 10.00},
    {"id": 7, "code": "WC060", "name": "Income Payment to Contractors", "rate": 2.00}
  ],
  "default_vat_category": "VATABLE"
}
```

Returns `{"withholding_taxes": [], "default_vat_category": null}` if vendor has no WHT codes configured.

---

## Form Changes

### `PurchaseBillForm`

Remove `withholding_tax_rate` field entirely.

### Template — header

Remove the `render_field(form.withholding_tax_rate)` row.

### Template — line items table

Add **WHT** column between VAT and Account:

```
# | Description | Qty | Unit Cost | VAT | WHT | Account | ×
```

WHT cell renders a `<select>`:
- `<option value="">None</option>`
- One `<option>` per vendor WHT code
- If vendor has no WHT codes: single disabled option `"No WHT configured"`

---

## JavaScript Behaviour

### On vendor change

1. Fetch `GET /vendors/<id>/defaults`
2. Store `currentVendorWHTs` (array) and `currentVendorVatCategory` (string)
3. For every existing line item row:
   - Re-render its WHT `<select>` from `currentVendorWHTs` (preserve selection if `wt_id` still in new list; otherwise reset to None)
   - Update its VAT category `<select>` to `currentVendorVatCategory`
4. New line items added after vendor change default to `currentVendorVatCategory` pre-selected

### `calculateTotals()`

Replace:
```js
const wtRate = parseFloat(document.querySelector('[name="withholding_tax_rate"]')?.value || 0);
const wtAmount = subtotal * wtRate / 100;
```

With:
```js
let wtAmount = 0;
lineItems.forEach(item => {
    const lineTotal = (item.quantity || 0) * (item.unit_cost || 0);
    wtAmount += lineTotal * ((item.wt_rate || 0) / 100);
});
```

### `updateLineItem()` — WHT selection

When WHT changes on a line item:
- Set `item.wt_id` to selected option value (int or null)
- Set `item.wt_rate` to selected option's rate (from `currentVendorWHTs`)
- Recalculate totals

### Form submit serialisation

Include in line items JSON payload:
```js
{ ..., wt_id: item.wt_id, wt_rate: item.wt_rate }
```

---

## Views — Server-side Changes

### `create` and `edit`

- Remove `withholding_tax_rate` from form processing
- Set `bill.withholding_tax_rate = Decimal('0.00')` on new/edited bills
- For each line item in submitted JSON:
  - Read `wt_id` (int or null)
  - If `wt_id` is set: look up `WithholdingTax` by id, snapshot `wt_rate`, compute `wt_amount = line_total × wt_rate / 100`
  - If `wt_id` is null: `wt_rate = None`, `wt_amount = Decimal('0.00')`

### Detail template — line items table

Add WHT column showing `{wt.code} ({wt_rate}%)` and `wt_amount` per line. Show `—` if no WHT on that line.

---

## Audit Trail

No new audit actions. Existing `create` / `update` audit entries capture the bill snapshot, which now implicitly includes line-level WHT via `total_amount` and `withholding_tax_amount`.

---

## Out of Scope

- WHT on Sales Invoices (separate feature)
- WHT on Receipts / Payments
- Retroactive update of existing posted bills
- BIR 2307 (Creditable WT certificate) generation
