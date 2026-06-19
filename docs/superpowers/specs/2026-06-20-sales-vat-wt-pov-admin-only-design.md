# Sales VAT Categories + WT Seller POV + Admin-Only Tax Maintenance — Design

**Date:** 2026-06-20
**Status:** Approved (brainstorm), pending implementation plan
**Author:** Claude (brainstorming session with owner)

## Problem & Intent

Tax reference maintenance in CAS currently uses **one shared table per tax type** that serves both the purchase (AP/CDV) and sales (SI/CRV) books:

- `VATCategory` carries *both* `input_vat_account_id` (purchase) and `output_vat_account_id` (sales) on a single row.
- `WithholdingTax` carries one `code` (ATC) + one `name`, written from the **buyer/payor** POV ("Professional Fees - Individuals", "Purchases of Goods"), reused verbatim on both books.
- Write access is `accountant` or `admin`; view is any authenticated user.

The owner wants three changes:

1. **Sales VAT gets its own maintenance, with different options.** The sales side needs a distinct category list and a sales-only classifier; it should not be entangled with purchase VAT.
2. **WT gains a seller-POV name on the same ATC.** The ATC code is shared, but sales documents should display a seller/payee-perspective name instead of the buyer-perspective one.
3. **All VAT + WT maintenance becomes admin-only**, view and write, with an admin-to-admin approval workflow. Accountants are fully removed from these modules.

## Decisions (locked during brainstorm)

| Topic | Decision |
|---|---|
| Sales VAT modeling | **Approach A — two separate models.** New `SalesVATCategory` blueprint *alongside* the existing `VATCategory`, which becomes purchase-only. |
| Sales VAT extra option | A `transaction_nature` classifier (sales-only). |
| WT seller name | **One record per ATC + a new `sales_name` field.** Not a separate WT table. |
| Access | **Admin-only**, view + write, on `vat_categories`, `sales_vat_categories`, `withholding_tax`. No accountant view/write/propose/review. |
| Approval | **Admin-to-admin.** Sole active admin self-approves; ≥2 admins → pending, a *different* admin approves; self-approval blocked. |
| Sales VAT codes | **New distinct `SVAT-*` codes** (clarity over backward-compat with old shared codes). |

## Section 1 — Data Model

> Per CLAUDE.md, every `models.py` change was described and signed off before this spec. This section is the source of truth for the migration.

### 1a. New model `SalesVATCategory` (new blueprint `app/sales_vat_categories/`)

| Field | Type | Null | Default | Notes |
|---|---|---|---|---|
| `id` | Integer PK | — | — | |
| `code` | String(20), unique | No | — | sales VAT code |
| `name` | String(100) | No | — | seller-POV name |
| `description` | Text | Yes | NULL | |
| `rate` | Numeric(5,2) | No | — | output VAT % |
| `transaction_nature` | String(30) | No | `'regular'` | one of `regular` / `zero_export` / `zero_other` / `exempt` / `government` |
| `output_vat_account_id` | Integer FK→accounts.id | Yes | NULL | form-required when `rate > 0` (mirrors current input-account rule) |
| `is_active` | Boolean | No | True | |
| `created_at` / `created_by_id` / `updated_at` / `updated_by_id` | audit | — | — | same pattern as `VATCategory` |

### 1b. New model `SalesVATCategoryChangeRequest`

Exact mirror of `VATCategoryChangeRequest`: `action` ('create'/'update'/'delete'), `status` ('pending'/'approved'/'rejected'), `sales_vat_category_id` (nullable FK), `proposed_data` (JSON text), `requested_by_id`, `requested_at`, `reviewed_by_id`, `reviewed_at`, `review_notes`, `request_reason`. `get_change_data()` / `set_change_data()` helpers as on the existing model.

### 1c. `VATCategory` — drop `output_vat_account_id`

`VATCategory` becomes purchase-only (keeps `input_vat_account_id`). **Two-step, data-preserving migration:**

1. **Data migration:** for every existing `VATCategory` with `output_vat_account_id` set, create a matching `SalesVATCategory` (same `code` / `name` / `rate`, that output account). `transaction_nature` is derived best-effort: `rate > 0` → `regular`; `rate == 0` → `zero_export` as a safe default (a 0%-rate row can't be auto-distinguished from `exempt`, so an admin reviews/corrects these post-migration). Preserves historical SI/CRV code-string resolution for any live data.
2. **Drop** the `output_vat_account_id` column from `VATCategory`.

`VATCategoryForm.validate_output_vat_account_id` and the field are removed.

> Note: seeded dev DBs never populate `output_vat_account_id` (fixtures only set input), so step 1 copies **zero** rows there — the sales rows come from the seed (Section 4), not the migration. The data-copy exists for live/production DBs where an admin set output accounts manually.

### 1d. `WithholdingTax` — add `sales_name`

Add `sales_name` String(100), **nullable** (backfilled, *not* made NOT NULL — avoids breaking existing rows and the required-field-breaks-old-tests trap). `name` stays buyer POV; `sales_name` is seller POV. `WithholdingTaxChangeRequest.proposed_data` JSON simply carries the extra key — no change to that model's columns.

### Migration summary

One Alembic revision: create `sales_vat_categories` + `sales_vat_category_change_requests`; add `withholding_tax.sales_name`; copy output-bearing VAT rows → sales table, then drop `vat_categories.output_vat_account_id`.

## Section 2 — Access Control & Approval Workflow

### 2a. Admin-only gate (view + write) on `vat_categories`, `sales_vat_categories`, `withholding_tax`

Every route — list, detail, create, edit, delete, view-change-requests, review — requires `role == 'admin'`. Replace `accountant_or_admin_required` with an `admin_required` gate per blueprint (mirroring `app/users/views.py::admin_required`: flash + redirect to dashboard for non-admins). List/detail are no longer `@login_required`-only — non-admins are redirected (the "no viewing rights" decision).

### 2b. Admin-centric approval (replaces the sole-accountant rule)

- `can_auto_approve()` for these modules → **True only when actor is admin AND exactly one active admin exists** (sole admin self-applies immediately, audit note "Auto-approved (single admin)").
- ≥2 active admins → change goes **pending**; `can_be_approved_by(username)` blocks self-approval, so a **different** admin must approve/reject.
- Rejections log `action='reject'` and notify the requester (unchanged mechanics).
- Applies identically to `VATCategoryChangeRequest`, `SalesVATCategoryChangeRequest`, `WithholdingTaxChangeRequest`.

### 2c. Sidebar nav visibility

VAT Categories, Sales VAT Categories, and Withholding Tax menu entries render **only for admins** (template role-gate matching the route gate). Grep `base.html` for all three labels to gate every twin (per grep-siblings).

### 2d. Out of scope / unchanged

The `book_permissions` per-module staff registry is not involved (these are not staff-gated transaction books). Consuming transaction forms (AP/SI/CDV/CRV) still **read** the active VAT/WT lists to populate dropdowns — reading populated choices is not "maintenance," so those forms keep working for non-admins.

## Section 3 — Consumer Rewiring

### 3a. Sales-side VAT source switch → `SalesVATCategory`

- Sales Invoice line items (`SalesInvoiceItem.vat_category` dropdown).
- Cash Receipt revenue lines (`CRVRevenueLine.vat_category` dropdown).
- Customer `default_vat_category` ("Registration Type" picker).
- The posting/JE logic that resolves the **output** VAT account by code moves from `VATCategory.output_vat_account_id` to `SalesVATCategory.output_vat_account_id`. (Exact resolution site to be traced during TDD; line items store the code as a string snapshot, so historical posted docs are unaffected.)

### 3b. Purchase-side unchanged

AP line items, CDV expense lines, and **vendor** `default_vat_category` keep reading `VATCategory` (now input-account-only). No behavior change beyond the dropped output column.

### 3c. WT label by side (POV-aware display)

- AP / CDV / **vendor** WT picker → `code — name` (buyer POV, unchanged).
- SI / CRV / **customer** WT picker → `code — sales_name`, **falling back to `name` when `sales_name` is empty** (nullable/backfilled). `wt_id` is still stored; submission/posting unchanged.
- The populate-WT-choices utility gains a `side`/`pov` parameter; find every caller (AP, CDV, SI, CRV, vendor, customer) and pass the correct POV.

### 3d. New cache + populate helpers

Add `get_active_sales_vat_categories()` + `clear_sales_vat_category_cache()` (1-hour memoize, mirroring `clear_account_cache`); the sales VAT maintenance calls the clear function after every mutation/approval. The VAT-choice populate utility splits into purchase vs sales variants.

### Ripple checklist (captured so nothing silently breaks)

SI/CRV forms + posting · customer form · vendor form (POV only) · AP/CDV WT label · `cache_helpers.py` · `vendors/utils.py` + `customers/utils.py` populate functions · audit module name `sales_vat_categories` · `base.html` nav (3 gated entries) · `regression-map.json` (new module + dependents) · seed (`app/fixtures.py` **and** `app/seeds/seed_data.py`).

## Section 4 — Seed / Migration Data

> Proposed and approved during brainstorm. Output VAT account = code `2100` "Output Tax"; input = `1200` "Input Tax".

### 4a. Sales VAT Categories to seed (rated rows → output account `2100`)

| code | name (seller POV) | rate | transaction_nature | output acct |
|---|---|---|---|---|
| `SVAT-G` | Sale of Goods (12%) | 12.00 | `regular` | 2100 |
| `SVAT-S` | Sale of Services (12%) | 12.00 | `regular` | 2100 |
| `SVAT-EX` | VAT-Exempt Sales | 0.00 | `exempt` | — |
| `SVAT-ZR` | Zero-Rated Sales (Export) | 0.00 | `zero_export` | — |
| `SVAT-GOV` | Sales to Government (12%) | 12.00 | `government` | 2100 |

### 4b. WT `sales_name` backfill (seller POV; `name` stays buyer POV)

| code | `name` (buyer, unchanged) | `sales_name` (seller) |
|---|---|---|
| WC010 | Professional Fees - Individuals | Professional Fees Income - Individual |
| WC011 | Professional Fees - Corporations | Professional Fees Income - Corporation |
| WC100 | Contractors & Subcontractors | Income as Contractor/Subcontractor |
| WC158 | Purchases of Goods | Sale of Goods (subject to 1% CWT) |

Both `flask seed-db` and `seed-minimal` (and the second path `app/seeds/seed_data.py`) get the sales rows + `sales_name` backfill. All values are admin-editable post-seed.

## Section 5 — Testing, Stale-Test Fallout & Rollout

### 5a. New tests (TDD-first)

- `SalesVATCategory` + `SalesVATCategoryChangeRequest`: model, CRUD via views, **audit entry asserted on every write**, `transaction_nature` validation, output-account-required-when-rate>0.
- Admin-only access on all three modules: accountant/staff/viewer redirected (view *and* write); admin allowed.
- Approval workflow: sole-admin auto-approve; ≥2 admins → pending + different-admin approval; self-approval blocked.
- WT `sales_name`: stored, shown on sales-side picker with fallback to `name`.
- Consumer wiring: SI/CRV VAT dropdown from sales table; customer default from sales table; vendor/AP/CDV still purchase table.
- Migration: data-copy of output-bearing `VATCategory` → `SalesVATCategory`, then column drop.

### 5b. Stale tests this will break (expected; fixed as test-only updates, each flagged)

- Any VAT/WT test that logs in as **accountant** to create/edit → switch actor to admin (includes sole-accountant auto-approve tests → sole-admin).
- The **Tier-1 VAT output-account validation tests** — that field/validation is removed from `VATCategoryForm`, so those assertions invert (the *inverse* of the required-field trap: a requirement is being removed).
- `test_vat_create_form_toggle_driven_by_select_value` and neighbors — re-confirm against admin-only + dropped-field changes.

### 5c. Regression map + nav

Add `app/sales_vat_categories/` (+ dependents `sales_invoices`, `cash_receipts`, `customers`) to `regression-map.json`; gate the 3 nav entries in `base.html` to admin.

### 5d. Rollout phases (one spec, separate commits; auto-commit, no push)

1. Model + Alembic migration + admin-access lock on the two existing tables.
2. New Sales VAT blueprint end-to-end (model/form/views/templates/change-request/cache/audit).
3. WT `sales_name` + consumer rewiring + POV labels.
4. Seed both paths + regression map + stale-test sweep.

## Related Memory / Conventions

- Customers↔Vendors parity mirror (customer sales-side ↔ vendor purchase-side).
- Grep-siblings on fix (WT label callers, nav twins, two seed paths).
- Required-field-breaks-old-tests (and its inverse here: requirement removal).
- Document/audit/cache conventions per CLAUDE.md.
- Open follow-up already on backlog: the failing `test_customer_vat_label_unchanged` guard (label unified to "Registration Type") — adjacent to this work; resolve when touching the customer form.
