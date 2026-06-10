# Purchase Bill Totals Panel Redesign

**Date:** 2026-06-10  
**Scope:** `form.html` (totals panel HTML + JS) and `detail.html` (Jinja2 totals panel)  
**No model or view changes.**

---

## Goal

Replace the current 4-row totals panel with a 6-row layout that mirrors the BIR accounting flow: gross → strip VAT → add VAT back → net of WHT = Net Amount Payable.

---

## New 6-Row Layout

| # | Label | Formula | Edit |
|---|-------|---------|------|
| 1 | Gross Amount | `subtotal` (sum of VAT-inclusive line amounts) | read-only |
| 2 | Less: Input VAT | `round(autoVat, 2)` or override value | ✏️ pencil override |
| 3 | Net of VAT | `Gross Amount − Input VAT` | read-only |
| 4 | Add: Input VAT | same value as row 2 (no separate edit) | read-only |
| 5 | Less: Withholding Tax | `round(autoWt, 2)` or override value | ✏️ pencil override |
| 6 | Net Amount Payable | `Gross Amount − Withholding Tax` | read-only (bold, blue) |

Rows 3 and 4 are a visual decomposition of the gross amount: show the net-of-VAT base, then add VAT back. Row 4 always mirrors row 2 — there is no second pencil.

---

## Computation Rules

- `autoVat = Math.round(sum_of_per_line_vat * 100) / 100` — same as current
- `autoWt = Math.round(sum_of_per_line_wht * 100) / 100` — same as current
- `vatUsed` = override value if `vatOverrideActive`, else `autoVat`
- `wtUsed` = override value if `wtOverrideActive`, else `autoWt`
- `netOfVat = subtotal − vatUsed`
- `netAmountPayable = subtotal − wtUsed`

All values rounded to exactly 2 dp in display (`fmt()` helper, already present).

---

## Changes: `form.html`

### HTML — totals panel (lines ~112–161)

Replace current structure with:

```
Row 1 — Gross Amount         id="subtotalDisplay"           (rename from "Subtotal:")
Row 2 — Less: Input VAT ✏️   id="vatDisplay" + override UX  (existing, rename label)
Row 3 — Net of VAT            id="netOfVatDisplay"           (NEW element)
Row 4 — Add: Input VAT        id="vatAddBackDisplay"         (NEW element, read-only)
  ── thin separator ──
Row 5 — Less: WHT ✏️          id="wtDisplay" + override UX  (existing, rename label)
  ── thick separator ──
Row 6 — Net Amount Payable    id="totalDisplay"              (rename from "Net Payable:")
```

Label changes only (no ID changes): "Subtotal:" → "Gross Amount", "Net Payable:" → "Net Amount Payable".

### JS — `calculateTotals()` additions

After computing `vatUsed` and `wtUsed`, add:

```javascript
const netOfVat = subtotal - vatUsed;
document.getElementById('netOfVatDisplay').textContent = fmt(netOfVat);
document.getElementById('vatAddBackDisplay').textContent = fmt(vatUsed);
```

`vatAddBackDisplay` must also be updated inside `onVatOverrideInput()` and `revertVatOverride()` — wherever `vatDisplay` is updated, `vatAddBackDisplay` must receive the same value.

---

## Changes: `detail.html`

Replace the 4-row totals block (lines ~190–211) with the equivalent 6-row Jinja2 block:

```
Row 1 — Gross Amount:         ₱{{ '{:,.2f}'.format(bill.subtotal) }}
Row 2 — Less: Input VAT [MANUAL?]:  ₱{{ '{:,.2f}'.format(bill.vat_amount) }}
Row 3 — Net of VAT:           ₱{{ '{:,.2f}'.format(bill.subtotal - bill.vat_amount) }}
Row 4 — Add: Input VAT:       ₱{{ '{:,.2f}'.format(bill.vat_amount) }}
  ── thin separator ──
Row 5 — Less: WHT [MANUAL?]:  -₱{{ '{:,.2f}'.format(bill.withholding_tax_amount) }}
  ── thick separator ──
Row 6 — Net Amount Payable:   ₱{{ '{:,.2f}'.format(bill.total_amount) }}
```

MANUAL badge logic unchanged — badge appears on row 2 when `bill.vat_override`, on row 5 when `bill.wt_override`. Row 4 never shows a MANUAL badge.

---

## What Does NOT Change

- Override pencil UX (`startVatOverride`, `revertVatOverride`, `onVatOverrideInput`, WHT equivalents)
- Hidden form fields (`vat_override`, `vat_override_value`, `wt_override`, `wt_override_value`)
- All element IDs (`vatDisplay`, `wtDisplay`, `totalDisplay`, `subtotalDisplay`)
- JE posting logic in `views.py`
- All model fields
- CSS variables and styling conventions
