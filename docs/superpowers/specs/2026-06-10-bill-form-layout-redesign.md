# Bill Entry Form — Layout & Initial Loading Redesign

## Goal

Redesign `form.html` (create and edit modes) so that selecting a vendor is the explicit first step, line items are locked until vendor context is loaded, and the form state progression is visually clear. No backend changes.

## Decisions

- **Layout**: Progressive / vendor-first (Option A)
- **Locked state**: Full header visible but dimmed until vendor selected (Option A2)
- **Totals placement**: Bottom-right panel, unchanged (Option T1)
- **Vendor field treatment**: Amber "Step 1" card, top of form, full-width (Option V2)

## Layout — Create Mode (Initial Load)

Top to bottom:

### 1. Vendor Step Card (amber, full-width)

```
┌─────────────────────────────────────────────────────┐  ← amber border #f59e0b
│ STEP 1 — SELECT VENDOR                              │  ← #92400e uppercase label
│ [ Search or select a vendor...                  ▾ ] │  ← full-width <select>
└─────────────────────────────────────────────────────┘    bg #fffbeb
```

- Autofocused on page load
- Vendor select uses the existing WTForms `vendor_id` field (rendered manually, not via `render_field`)
- On vendor selected → transitions to green success state (see below)

### 2. Header Fields (dimmed until vendor selected)

`opacity: 0.65; pointer-events: none` applied to a wrapper `<div id="headerFields">` until vendor is selected. Transition: `opacity 0.2s ease`.

Field layout (unchanged from current):
- Row 1 (3 col): Bill # (read-only, auto-generated) · Bill Date · Due Date  
- Row 2 (2 col): Payment Terms · Vendor Invoice #
- Row 3 (2 col): Vendor Invoice Date · Reference
- Row 4 (1 col full): Notes

### 3. Line Items Zone (locked placeholder)

```
┌─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┐  ← dashed border #f59e0b
    🔒  Select a vendor above to add line items
        WHT codes and VAT defaults will load          ← font-size: 13px, #92400e
        from the vendor.
└─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┘    bg #fffbeb
```

- The actual line items table, "+ Add Line Item" button, and hidden `#lineItemsData` input are rendered in the DOM but wrapped in `<div id="lineItemsSection" style="display:none">`.
- The locked placeholder `<div id="lineItemsLocked">` is shown instead.

### 4. Totals Panel

Wrapped in `<div id="totalsPanel" style="display:none">`. Shown when vendor is selected. Layout unchanged from current (bottom-right, monospace values, Enter Bill button inside).

---

## State Transition: Vendor Selected

When the `vendor_id` select changes to a non-empty value:

1. **Fetch** `/vendors/{id}/defaults` (existing endpoint).
2. **Vendor card** → border `#22c55e`, background `#f0fdf4`, label changes to `✓ {vendor name}`, show inline badges for WHT code(s) and default VAT category.
3. **Header fields wrapper** → `opacity: 1; pointer-events: auto`.
4. **Payment Terms** → auto-fills from `data.payment_terms`.
5. **Due Date** → if terms matches `Net N`, compute `bill_date + N days`.
6. **Line items** → hide `#lineItemsLocked`, show `#lineItemsSection`, call `addLineItem()` (adds first row with vendor defaults pre-selected).
7. **Totals panel** → `display: block`.

All transitions use `transition: opacity 0.2s ease` on the relevant elements.

---

## Vendor Change After Line Items Exist

If vendor is changed after line items are already present:

- Do **not** clear existing line items.
- Re-run `rebuildAllWhtSelects()` and `rebuildAllVatSelects()` (existing functions, unchanged).
- Recompute payment terms and due date.
- Update vendor card to new vendor name + badges.

---

## Edit Mode (existing bill)

- Vendor card loads in **green completed state** immediately: border `#22c55e`, bg `#f0fdf4`, label `✓ {vendor name}`, WHT/VAT badges visible.
- Header fields wrapper at full opacity from initial render (no dimming).
- `#lineItemsLocked` hidden; `#lineItemsSection` visible from the start.
- `#totalsPanel` visible from the start.
- Existing JS init block (`{% if bill %}`) fetches vendor defaults then calls `initItems()` — unchanged in logic, but runs after the vendor card is set to completed state.

---

## What Does NOT Change

- Flask routes (`create`, `edit`) — no changes
- `PurchaseBill` model, `PurchaseBillForm` — no changes
- `generate_bill_number()`, line item calculation logic — no changes
- Line items table column structure (7 columns) — no changes
- Totals calculation JS (`calculateTotals()`) — no changes
- Submit serialisation (`lineItemsData` hidden input) — no changes

---

## Files Changed

- `app/purchase_bills/templates/purchase_bills/form.html` — full rewrite of template structure and JS init logic

No other files.

---

## Testing

Manual browser test (playwright or direct):

1. Navigate to `/purchase-bills/create`.
2. Assert: amber vendor card visible, header fields dimmed (`opacity` < 1), line items locked placeholder visible, totals panel hidden.
3. Select any vendor.
4. Assert: vendor card turns green with vendor name, header fields undim, first line item row appears with WHT/VAT pre-selected, totals panel visible.
5. Change vendor.
6. Assert: existing line items remain, WHT/VAT rebuilt, vendor card updates.
7. Navigate to `/purchase-bills/{draft_id}/edit`.
8. Assert: vendor card green on load, no dimming, line items visible immediately.
