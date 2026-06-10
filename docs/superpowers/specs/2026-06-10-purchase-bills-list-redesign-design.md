# Purchase Bills List Page Redesign — Design Spec

**Date:** 2026-06-10
**Status:** Approved by user
**Scope:** `/purchase-bills` list page only — template, `list_bills()` view, export routes, new helper module. **No model changes.**

## Background

The current page renders a bare table. Findings from review:

1. **Dead filters:** `list_bills()` reads `?status=` and `?vendor=` and passes a `vendors` list to the template, but the template renders no filter controls.
2. **WT column always shows `-₱0.00`**, even with no withholding.
3. **Status badges cover only 4 of 6 statuses** — `partially_paid`, `voided`, `cancelled` collapse into "danger"; local `.badge*` CSS redefines global classes from `style.css`.
4. No date-range filter, no search, no outstanding-balance column.
5. `datetime.now()` used in `generate_bill_number()` and both export routes (violates PH-time rule).

Layout chosen by user: **Option A — Summary Cards + Filter Bar** (display-only KPI cards; filtering happens in the filter bar). Page must serve both daily jobs: morning AP review and all-day bill encoding.

## Decisions & Scope Boundaries

- **Multi-bill payment vouchers are OUT of scope.** The `Receipt` model has no link to bills; nothing updates `bill.amount_paid` today. "Payment vouchers with bill application" is a separate future project (allocation table, payment form pulling open bills, status/balance updates, reversal logic). This redesign only leaves layout room for a future "Pay selected" button.
- **Checkboxes are IN scope but wired to export only.**
- **No bulk posting.** Posting stays one-bill-at-a-time.
- **Display-only cards** — cards do not act as filters (user chose A over the clickable-cards hybrid).

## Design

### 1. Summary cards

Four cards in a row above the filter bar, computed for the current branch (`session['selected_branch_id']`):

| Card | Metric | Detail line |
|---|---|---|
| Outstanding AP | `sum(balance)` over `posted` + `partially_paid` bills | "N open bills" |
| Overdue | same statuses, `due_date <` today (PH date); amount shown red | "N bills" |
| Due in 7 days | same statuses, `today <= due_date <= today+7` | "N bills" |
| Drafts | count of `draft` bills | "to finish" |

New module **`app/purchase_bills/utils.py`** (mirrors `app/vendors/utils.py`):

```python
def compute_bills_summary(branch_id):
    """Return dict: outstanding_total, outstanding_count, overdue_total,
    overdue_count, due_soon_total, due_soon_count, draft_count."""
```

- Uses `ph_now().date()` for today.
- One aggregate query per metric, all filtered by `branch_id`.
- `due_date` is `nullable=False` on the model, so no NULL handling is required; the helper still guards with `due_date.isnot(None)` defensively.
- Returns `Decimal('0.00')` / `0` values when there are no bills.

### 2. Filter bar

GET form, directly below the cards:

- **Search** `q` — case-insensitive contains-match on `bill_number` OR `vendor_name`
- **Status** dropdown — All, Draft, Posted, Partially Paid, Paid, Voided, Cancelled
- **Vendor** dropdown — active vendors (already passed to the template; finally used)
- **Date from / Date to** — inclusive range on `bill_date`
- **Filter** submit + **Clear** link (resets to `/purchase-bills`)

`list_bills()` changes:

- New params: `q`, `date_from`, `date_to` (ISO dates; invalid values silently ignored via `try/except ValueError` — same pattern as `vendors.detail`).
- Existing `status` / `vendor` params unchanged.
- All filter params carried through pagination links and both export URLs.
- Summary dict passed to the template (cards always reflect the branch, not the filtered subset).

### 3. Table

Columns: **☐ | Bill # | Date | Vendor | Due Date | Subtotal | VAT | WT | Net Payable | Balance | Status | Actions**

- **Checkbox column** — header checkbox = select-all; per-row checkboxes carry `bill.id`.
- **Balance column** — `bill.balance`, bold; shows `—` for `paid`/`voided`/`cancelled` bills.
- **WT column** — `—` when `withholding_tax_amount == 0`, otherwise `-₱X,XXX.XX` in red.
- **Due Date** — red when `due_date < today` and status is `posted`/`partially_paid`.
- **Status badges** — all 6 statuses mapped to existing global classes in `style.css`:
  `draft→badge-draft`, `posted→badge-posted`, `partially_paid→badge-partial`, `paid→badge-paid`, `voided→badge-void`, `cancelled→badge-cancelled`. Template uses a small Jinja mapping dict (same pattern as vendor detail bills tab).
- **Local `.badge*` CSS redefinitions deleted.** Only page-specific classes (cards, filter bar, `.btn-action`) stay local, all colors via design tokens (`var(--blue)`, `var(--red)`, `var(--amber)`, `var(--text-2)`, `var(--border)`, `var(--card)`, `var(--mono)`).

### 4. Selection → export

- "Export Excel" / "Export CSV" become forms that include selected `ids` when any row is checked; with no selection they export the current filtered set (today's behavior, plus new filters).
- Export routes accept optional `ids` (comma-separated ints); when present, `ids` overrides other filters. Invalid/foreign ids are ignored; bills are still branch-scoped.
- Small vanilla JS for select-all toggle and a "N selected" counter near the export buttons. No popups (no `confirm`/`alert`).
- Future "Pay selected" button slot documented in a template comment — not rendered.

### 5. Same-scope cleanups

- Replace `datetime.now()` with `ph_now()` in `generate_bill_number()`, `export_excel()`, `export_csv_route()` (PH-time rule; flagged in the 2026-06-09 final code review).

### 6. Responsive

- Cards: 4 columns → 2 (≤1024px) → 1 (≤640px) via CSS grid.
- Filter bar wraps (`flex-wrap`).
- Table stays horizontally scrollable inside the card on narrow screens.

### 7. Error handling

- Invalid `date_from`/`date_to`/`vendor`/`ids` values: ignored, never 500.
- Unknown `status` values: treated as `all`.
- Empty result set: existing empty-state kept, but message reflects active filters ("No bills match your filters" + Clear link) vs. truly empty ("No purchase bills found." + Create First Bill).

### 8. Testing (TDD — tests written first)

**Unit (`tests/unit/test_purchase_bills_utils.py`):**
- `compute_bills_summary` bucket math: outstanding/overdue/due-soon totals and counts, draft count, due-today boundary (in due-soon, not overdue).
- Status exclusions: `draft`/`paid`/`voided`/`cancelled` excluded from outstanding; `partially_paid` included with its `balance`.
- Branch scoping: bills in another branch excluded.
- Empty branch returns zeros.

**Integration (`tests/integration/test_purchase_bill_views.py`):**
- Cards render with correct computed totals.
- Each filter narrows results (status, vendor, date range, search by bill # and by vendor name).
- Filter params preserved in pagination links.
- Export with `ids` returns only selected bills; export without `ids` respects filters.
- Staff/viewer can view list; write actions remain accountant/admin-only.
- No `confirm(` in rendered page.

No new audit assertions: the page is read-only (exports are not audited today; parity kept).

## Files

| File | Change |
|---|---|
| `app/purchase_bills/utils.py` | **Create** — `compute_bills_summary` |
| `app/purchase_bills/views.py` | Modify — `list_bills` filters/search/summary; export `ids`; `ph_now()` cleanups |
| `app/purchase_bills/templates/purchase_bills/list.html` | Rewrite — cards, filter bar, table, selection, CSS |
| `tests/unit/test_purchase_bills_utils.py` | **Create** |
| `tests/integration/test_purchase_bill_views.py` | **Create** |
