# AR Aging Report Implementation Design

**Date:** 2026-06-19  

> **⚠️ SUPERSEDED (2026-06-19) — do not implement as written.** Two parts of this
> spec were rejected by the shipped code:
> - **Task 2 (badge hex):** instructed hardcoded inline hex (`#dcfce7`, `#d97706`,
>   etc.). This violates the "No hardcoded styling — use design tokens" rule.
>   Reversed by commit `cd0fb2c` (now uses `--aging-*` CSS variables).
> - **Task 3 (export columns):** specified a per-invoice export. Shipped as a
>   per-customer/vendor **bucket summary** in commit `154fbaf`.
> The view-activation and aging-bucket logic remain accurate; treat the styling
> and export sections as historical only.

**Goal:** Activate the blocked AR Aging report — remove the blocking redirect, align the template to the current design system (matching AP Aging), add `invoice_id` for deep-links, and wire up Excel/CSV export routes.

---

## Overview

The AR Aging report shows accounts receivable (customer invoices) grouped by customer and aged into buckets: current, 1-30, 31-60, 61-90, and 90+ days overdue. The logic already exists in `app/reports/views.py:74-146` but is blocked by an early `return redirect(...)` statement. The template exists but uses outdated design tokens and lacks export links.

**This is a 1:1 parallel of the AP Aging implementation just completed** — same structure, same test coverage, same exports. The only difference: AR works with `SalesInvoice` (seller's perspective) instead of `PurchaseBill` (buyer's perspective).

---

## Architecture

**Data source:** `SalesInvoice` with `status in ('posted', 'partially_paid')` and `balance > 0`, scoped to the current branch.

**Aging buckets:** Calculated by comparing invoice due date to a user-supplied "as of" date (default: today):
- **Current:** Due date >= as_of_date
- **1-30:** 1-30 days overdue
- **31-60:** 31-60 days overdue
- **61-90:** 61-90 days overdue
- **90+:** 91+ days overdue

**Grouping:** By customer name. Within each customer, list all invoices with their aging bucket and days overdue.

**Grand totals:** Sum of all customers' amounts in each bucket.

**Helper function:** `calculate_age_bucket(due_date, as_of_date)` — already exists in `app/reports/views.py` and is shared with AP Aging. Requires unit test coverage.

---

## Files to Create/Modify

| File | Action | Task |
|---|---|---|
| `tests/unit/test_ar_aging.py` | Create | 1 |
| `app/reports/templates/reports/ar_aging.html` | Rewrite | 2 |
| `app/reports/views.py` | Modify lines 74–146 + append export routes | 3 |
| `tests/integration/test_ar_aging_views.py` | Create | 4 |

---

## Task 1: Unit Tests for `calculate_age_bucket`

**Files:** Create `tests/unit/test_ar_aging.py`

**Coverage:** All 5 bucket transitions (current, 1-30, 31-60, 61-90, 90+) plus edge cases (None due date, future date, boundary dates).

**Test count:** 11 tests (same as AP Aging tests).

**Notes:**
- No DB fixtures needed — pure logic tests.
- Function already exists and is shared with AP Aging, so all tests should PASS immediately.
- Test class: `TestCalculateAgeBucket` with methods for each bucket and boundary case.

---

## Task 2: Rewrite Template — Design System Alignment

**Files:** Rewrite `app/reports/templates/reports/ar_aging.html`

**Current issues in the existing template:**
- `class="content-card"` → should be `class="card"`
- `class="text-right"` → should be inline `style="text-align:right"`
- `class="text-muted"` → should be inline `style="color:var(--text-2)"`
- `var(--background)` → should be `var(--bg)`
- `var(--surface)` → should be `var(--card)`
- `var(--warning)` → should be `#d97706`
- `var(--danger)` → should be `var(--red)`
- Badge classes (`badge-success`, `badge-warning`, `badge-danger`) → should be inline span badges with hardcoded colors
- Missing export buttons (Excel, CSV)
- Invoice number lacks a link to the sales invoice detail view

**Design tokens to apply:**

| Old | New |
|---|---|
| `class="content-card"` | `class="card"` |
| `class="text-right"` | `style="text-align:right"` |
| `class="text-muted"` | `style="color:var(--text-2)"` |
| `var(--warning)` | `#d97706` |
| `var(--danger)` | `var(--red)` |
| `var(--background)` | `var(--bg)` |
| `var(--surface)` | `var(--card)` |
| `var(--primary)` | `var(--blue)` |
| `badge-success` | `<span style="background:#dcfce7;color:#166534;border-radius:4px;padding:2px 8px;font-size:11px;font-weight:600;">…</span>` |
| `badge-warning` | `<span style="background:#fef9c3;color:#854d0e;border-radius:4px;padding:2px 8px;font-size:11px;font-weight:600;">…</span>` |
| `badge-danger` | `<span style="background:#fee2e2;color:#991b1b;border-radius:4px;padding:2px 8px;font-size:11px;font-weight:600;">…</span>` |

**New elements:**
- Export buttons in the card header: "Excel", "CSV"
- Invoice number rendered as a link: `<a href="{{ url_for('sales_invoices.view', id=invoice.invoice_id) }}">{{ invoice.invoice_number }}</a>`
- All styles migrated to inline or design tokens

---

## Task 3: Activate View + Fix Query + Add Export Routes

**Files:** Modify `app/reports/views.py` lines 74–146 + append export routes

**Changes to `ar_aging()` view:**
1. Remove the line: `return redirect(url_for('dashboard.under_development', feature='AR Aging'))`
2. Add `ValueError` guard on `date.fromisoformat()` (fallback to today if invalid)
3. Change status filter from `== 'posted'` to `.in_(['posted', 'partially_paid'])` — matches AP Aging and SalesInvoice status set
4. Add `invoice_id` to the invoice dict (needed for template link to sales invoice detail)
5. Use `max(0, ...)` guard on `days_overdue` calculation

**New export routes:**
- `GET /reports/ar-aging/export/excel` → Excel file with all invoices
- `GET /reports/ar-aging/export/csv` → CSV file with all invoices

Both routes accept the same `?as_of=YYYY-MM-DD` query param as the main view.

**Export columns:** invoice_number, customer_name, invoice_date, due_date, balance, bucket, days_overdue

---

## Task 4: Integration Tests for AR Aging View and Exports

**Files:** Create `tests/integration/test_ar_aging_views.py`

**Test coverage:**
- Page loads (GET `/reports/ar-aging` returns 200)
- Empty state (no invoices → "No outstanding receivables" message)
- Posted invoice with balance appears in report
- `partially_paid` invoice with balance appears in report
- Paid/voided/cancelled/draft invoices do NOT appear
- Overdue invoices fall into correct aging buckets
- Date filter works (`?as_of=YYYY-MM-DD`)
- Invalid as_of date falls back to today without crashing
- Invoice number links to sales invoice detail view
- Excel export returns a file with xlsx magic bytes
- CSV export returns a file with headers

**Test fixtures:**
- Use existing `admin_user`, `main_branch` from `conftest.py`
- Create helper functions: `login()`, `set_branch()`, `make_invoice()` — no separate `make_customer()` needed since `SalesInvoice.customer_name` is a plain string column (no FK to a Customer model)
- All tests follow the pattern: login → set branch → create test data → assert response

**Test count:** 10+ integration tests

---

## Implementation Order (TDD)

**Parallelizable:**
- Task 1 (unit tests) and Task 2 (template rewrite) can run in parallel — no dependencies

**Sequential:**
- Task 3 (view activation + exports) must come AFTER Tasks 1 and 2 are complete
- Task 4 (integration tests) must come AFTER Task 3

---

## Acceptance Criteria

✅ All 11 unit tests pass  
✅ Template renders with no design token violations  
✅ `/reports/ar-aging` loads and displays customer aging summary  
✅ Invoice numbers are clickable links to sales invoice detail  
✅ Excel export returns a valid .xlsx file  
✅ CSV export returns a valid .csv file  
✅ Date filter works and resets as_of_date correctly  
✅ All 10+ integration tests pass  
✅ No regressions in other report tests  

---

## Notes

- The `calculate_age_bucket()` helper is shared with AP Aging and already tested there, but we write unit tests here for AR's integration test suite to import and verify.
- All design token changes in the template match those applied to AP Aging (`2026-06-14-ap-aging.md`), ensuring visual consistency across aging reports.
- Invoice deep-links use `sales_invoices.view` (not `purchase_bills.view`); confirm this route exists and takes `id` parameter.
- No changes to VAT Categories, WHT codes, or Chart of Accounts — AR Aging is purely a reporting layer on top of existing Sales Invoice data.
