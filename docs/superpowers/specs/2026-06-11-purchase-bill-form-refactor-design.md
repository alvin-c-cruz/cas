# Purchase Bill Form — Refactor & Polish Design

**Date:** 2026-06-11
**Scope:** `app/purchase_bills/templates/purchase_bills/form.html` and new static assets
**Goal:** Extract CSS and pure-JS utilities into reusable static files; add responsive breakpoints; gate Save Draft on minimum required data.

---

## 1. File Structure

Four files replace the current single 938-line template.

### `app/static/transactions.css` *(new — shared)*
Styles reusable across all transaction forms (purchase bills, sales invoices, receipts). Contains:
- Choices.js compact overrides (`.choices`, `.choices__inner`, `.choices__list--dropdown`, etc.)
- Amount input styles (text-align right, monospace font)
- Header layout grid: `.form-main-grid`, `.left-col-fields`, `.right-col`, `.notes-col`
- Summary panel: `.bsr`, `.bsr-amt`, `.bsr-label`, `.bsr-hint`, `.bsr-amt-wrap`, `.bsr--sep`, `.bsr--total`
- `.btn-action` (delete button in line item tables)
- Responsive breakpoints (see §3)

### `app/static/purchase_bills_form.css` *(new — bill-specific)*
Styles that only apply to the purchase bill form. Contains:
- Vendor step card (`.vendor-step-card`, `.vendor-step-label`, `.vendor-badges`, `.vendor-badge`)
- Header field dimming (`.header-fields`, `.header-fields--active`)
- Line items locked placeholder (`.line-items-locked`, `.line-items-locked--hidden`)
- Totals override UX (`.totals-pencil`, `.totals-revert`, `.bsr-input`)
- Bill Summary panel (`.bill-summary-panel`)
- Line items table compaction (`#lineItemsTable` rules)

### `app/static/transaction-utils.js` *(new — shared)*
Pure utility functions with no DOM access, no global state, no Jinja dependencies. Safe to load as a static file on any transaction form. Exports (as globals):
- `fmt(n)` — locale number format (en-PH, 2 decimal places)
- `amtFmt(n)` — same with zero fallback
- `amtFocus(el)` — strip commas, select-all on focus
- `amtBlur(el, id)` — reformat on blur, call `updateLineItem`
- `escHtml(s)` — HTML escape for Choices.js templates

> **Note:** `amtBlur` calls `updateLineItem(id, 'amount', n)` which is defined in the inline form script. Document this at the top of `transaction-utils.js` with a comment: `// amtBlur expects updateLineItem(id, field, value) to be defined by the host form.`

### `form.html` *(trimmed)*
- Loads `transactions.css`, `purchase_bills_form.css`, `choices.min.css` in `<head>`
- Loads `choices.min.js`, `transaction-utils.js` before the inline `<script>`
- Top-level content `<div>` gets class `page-purchase-bill` (CSS scoping anchor — see §2)
- Small inline `<script>` at top of the script block injects Jinja data:
  ```js
  const vatCategories = {{ vat_categories | tojson }};
  const allAccounts   = {{ all_accounts   | tojson }};
  const glAccounts    = {{ gl_accounts    | tojson }};
  ```
- All form logic JS (lineItems state, addLineItem, calculateTotals, vendor handler, etc.) remains inline
- No `<style>` block

---

## 2. CSS Scoping

The outer `<div class="card">` gains an additional class: `page-purchase-bill`. Any rule in `transactions.css` that could conflict with another form when that form's CSS is loaded gets prefixed:

```css
/* example — scoped override */
.page-purchase-bill .choices__list--dropdown { min-width: 260px; }
```

Rules that are safe globally (Choices.js base overrides, `.bsr` layout, `.btn-action`) stay unscoped. Bill-specific rules in `purchase_bills_form.css` are already implicitly scoped by their class names.

---

## 3. Responsive Breakpoints

All breakpoints go in `transactions.css`.

### Tablet — max-width: 1023px
- `.form-main-grid` switches from `grid-template-columns: 1fr 2fr` to `grid-template-columns: 1fr` (single column)
- Stacking order: vendor card → header fields → notes → line items → JE preview → Bill Summary
- DOM order is `left-col-fields` before `right-col`, so CSS `order` is required to achieve vendor-first stacking:
  ```css
  @media (max-width: 1023px) {
    .left-col-fields { order: 2; }
    .right-col       { order: 1; }
  }
  ```
- JE preview + Bill Summary section switches from side-by-side to `flex-direction: column`
- Bill Summary `min-width` removed (becomes full width)

### Mobile — max-width: 639px
- Same stacking order as tablet
- `.left-col-fields .form-group` switches to `flex-direction: column; align-items: flex-start` (label above input)
- `#lineItemsTable` wrapper gets `overflow-x: auto` — table scrolls horizontally (intentional; this is a desktop-primary data-entry form)
- `.form-main-grid` gap reduced to 12px

---

## 4. Save Draft — Gating

The Save Draft button starts **disabled** and becomes enabled only when all minimum requirements are satisfied. A one-line hint below the button explains what is still missing.

### Implementation
- `validateForm()` function runs at the end of `calculateTotals()` and on every line item change
- Returns `{ valid: boolean, hint: string | null }`
- Sets `submitBtn.disabled = !valid` and updates a `<p id="saveHint">` element

### Minimum Requirements

| Field | Rule |
|---|---|
| Vendor | Must be selected (already enforced by locked state) |
| Vendor Invoice # | Must be non-empty |
| Line items | At least one must exist |
| Account Title (each line) | Must be selected |
| Amount (each line) | Must be > 0 |
| Description (each line) | Required only when 2+ line items exist; optional for a single-line bill (header Notes serves as narrative) |

### Hint Messages (priority order — first failing rule shown)
1. "Select a vendor" — (edge case; locked state should prevent this)
2. "Enter the vendor invoice number"
3. "Add at least one line item"
4. "Line [N]: select an account title"
5. "Line [N]: enter an amount greater than zero"
6. "Line [N]: enter a description" — (only shown when 2+ lines)

---

## 5. Playwright Smoke Test

**File:** `tests/smoke/test_purchase_bill_form.py`
**Marker:** `smoke` (added to `pytest.ini`)
**Runner:** `pytest -m smoke`

### Coverage

| Step | Assertions |
|---|---|
| Page load | 200 response; "Save Draft" button present but disabled; line items section hidden |
| Vendor Invoice # empty | Save Draft still disabled after vendor select |
| Vendor selected | Header fields active; line items visible; one row auto-added; VT pre-filled |
| Vendor Invoice # filled | Save Draft still disabled if Account Title blank |
| Account + amount filled | Save Draft becomes enabled |
| Submit | Redirects to bill detail; bill appears in /purchase-bills list |

---

## 6. Out of Scope

- Sales invoice or receipt form changes (they will adopt `transactions.css` and `transaction-utils.js` when they get the Choices.js / amount-formatting treatment — no changes to those forms in this spec)
- Any backend model or view changes
- Draft vs. posted status workflow (Save Draft is currently cosmetic naming; no status field change)
