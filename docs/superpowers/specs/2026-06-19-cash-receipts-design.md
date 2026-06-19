# Cash Receipt Voucher (CRV) Module — Design Spec

**Date:** 2026-06-19
**Status:** Approved (design), pending spec review

## Context

The application has a fully-working **Cash Disbursement Voucher (CDV)** module (`app/cash_disbursements/`) that records vendor payments: it applies amounts against open AP bills, posts a balanced journal entry, reduces bill balances, and supports void/reversal. The **receipt** side has no working equivalent — the legacy `receipts` blueprint is blocked behind an `under_development` redirect, posts no journal entry, and has no link to sales invoices.

This spec defines a new **Cash Receipt Voucher (CRV)** module built as the exact AR-side mirror of CDV. It lets a user record a customer collection, apply it against one or more open sales invoices (reducing their AR balance), and/or record direct revenue/other-income received outside an invoice — all with proper GL posting. It also activates the stubbed Cash Receipts Journal report. The result: AR Aging becomes dynamic (collections reduce aged balances live), completing the symmetry with the AP/disbursement side.

**Confirmed decisions:**
- Build a **new `cash_receipts` module (CRV)** mirroring CDV; **retire** the legacy `receipts` blueprint.
- A receipt supports **both** invoice-application lines **and** direct revenue lines.
- **Include** the `/journals/cr` Cash Receipts Journal report in this effort.

## Goals

1. A working CRV transaction: create → post → void, scoped per branch, role-gated.
2. Apply a collection across one or more open sales invoices, reducing `SalesInvoice.balance` and flipping status to `partially_paid`/`paid`.
3. Support direct revenue lines (cash sale / misc income) with VAT extraction and optional WHT.
4. Post a balanced journal entry on post; reverse it (and the AR application) on void.
5. Activate the columnar Cash Receipts Journal (`/journals/cr`) + xlsx export.
6. Retire the legacy `receipts` blueprint cleanly; repoint navigation/permissions.

## Non-Goals

- Multi-currency, partial-void of individual lines, or receipt editing after post (matches CDV: post is terminal except void).
- Replacing the demo seed script's simulated partial payments with real CRVs (separate follow-up).
- Bank reconciliation / check-clearing workflow (the legacy `Receipt` model had `cleared`/`bounced` states; CRV does not replicate them — out of scope).

## Architecture

New blueprint package `app/cash_receipts/`, structured identically to `app/cash_disbursements/`:

| File | Responsibility |
|---|---|
| `models.py` | `CashReceiptVoucher`, `CRVArLine`, `CRVRevenueLine` |
| `forms.py` | `CashReceiptForm` (mirror of `CashDisbursementForm`) |
| `views.py` | routes (list/create/view/post/void/cancel), JE posting, AR application, open-invoice JSON endpoint |
| `utils.py` | helpers (e.g. AR-aging-free helpers if needed) |
| `templates/cash_receipts/` | list, form, detail templates (mirror CDV templates) |

Registered explicitly in `app/__init__.py::create_app` (model imports + blueprint registration list), per the project's explicit-registration convention. The legacy `receipts` model import and `receipts_bp` registration are **removed** in the same change.

Numbering: **`CR-YYYY-MM-NNNN`**, generated per (prefix, year, month), mirroring CDV's `CD-YYYY-MM-NNNN` (`generate_*_number` helper in `cash_disbursements`). Note: the legacy `Receipt` model also used a `CR-` prefix; since that module is retired and its routes never created posted data through normal navigation, collisions are not a concern, but the generator queries existing `crv_number` values only (its own table).

## Data Model (new tables — explicitly approved)

One Alembic migration creates three tables. Field shapes mirror the CDV tables verbatim except AP→AR / vendor→customer / expense→revenue.

### `cash_receipt_vouchers` (`CashReceiptVoucher`)
| Column | Type | Notes |
|---|---|---|
| `id` | Integer PK | |
| `branch_id` | FK→branches | not null, indexed |
| `crv_number` | String(50) | unique, not null, indexed |
| `crv_date` | Date | not null, indexed |
| `customer_id` | FK→customers | not null, indexed |
| `customer_name` | String(200) | not null (snapshot) |
| `customer_tin` | String(20) | nullable |
| `payment_method` | String(20) | not null, default `'cash'` (cash/check/bank_transfer/online) |
| `check_number` / `check_date` / `check_bank` | String/Date/String | nullable |
| `cash_account_id` | FK→accounts | not null (the Dr Cash/Bank account) |
| `notes` | Text | not null, default `''` |
| `total_ar_applied` | Numeric(15,2) | default 0, not null |
| `total_revenue` | Numeric(15,2) | default 0, not null |
| `total_vat` | Numeric(15,2) | default 0, not null |
| `total_wt` | Numeric(15,2) | default 0, not null |
| `total_amount` | Numeric(15,2) | default 0, not null |
| `vat_override` / `wt_override` | Boolean | default False, not null |
| `status` | String(20) | default `'draft'`, not null, indexed (draft/posted/voided/cancelled) |
| `journal_entry_id` | FK→journal_entries | nullable |
| `created_by_id`/`posted_by_id`/`voided_by_id` | FK→users | nullable |
| `created_at`/`updated_at` | DateTime | `ph_now`, not null |
| `posted_at`/`voided_at`/`cancelled_at` | DateTime | nullable |
| `void_reason` | String(255) | nullable |
| `cancel_reason` | String(500) | nullable |

Relationships: `ar_lines` (CRVArLine, cascade delete-orphan, ordered by line_number), `revenue_lines` (CRVRevenueLine, same).

`calculate_totals()`:
```
total_ar_applied = Σ ar_lines.amount_applied
total_revenue    = Σ revenue_lines.line_total
total_vat        = Σ revenue_lines.vat_amount        (unless vat_override)
total_wt         = Σ revenue_lines.wt_amount         (unless wt_override)
total_amount     = total_ar_applied + total_revenue − total_wt
```

### `crv_ar_lines` (`CRVArLine`)
| Column | Type | Notes |
|---|---|---|
| `id` | Integer PK | |
| `crv_id` | FK→cash_receipt_vouchers | not null, indexed |
| `line_number` | Integer | not null |
| `invoice_id` | FK→sales_invoices | not null |
| `invoice_number` | String(50) | not null (snapshot) |
| `original_balance` | Numeric(15,2) | not null (invoice balance at time of application) |
| `amount_applied` | Numeric(15,2) | not null |

### `crv_revenue_lines` (`CRVRevenueLine`)
Mirror of `CDVExpenseLine`: `id`, `crv_id` (FK, not null, indexed), `line_number`, `description` (String(500), not null), `amount` (Numeric, gross VAT-inclusive), `vat_category` (String(100), nullable), `vat_rate` (Numeric, default 0, not null), `line_total` (Numeric), `vat_amount` (Numeric), `account_id` (FK→accounts, the revenue account), `wt_id` (FK→withholding_tax, nullable), `wt_rate` (Numeric, nullable), `wt_amount` (Numeric, default 0, not null). `calculate_amounts()` extracts VAT from the inclusive amount and computes WHT on the net base — identical to `CDVExpenseLine.calculate_amounts()`.

## Accounting (mirror of CDV, inverted)

GL accounts (reuse existing lookups): AR-Trade `10201`, Creditable WHT Receivable `10212`, Output VAT via `VATCategory.output_vat_account`, cash/bank from `cash_account_id`, revenue from each revenue line's `account_id`.

Posted JE (`entry_type='receipt'`, `entry_date=crv_date`, `reference=crv_number`):
- **Cr Accounts Receivable** — one line per AR line, `amount_applied` (mirrors CDV Dr AP)
- **Cr Revenue** — net base (`line_total − vat_amount`) per revenue line
- **Cr Output VAT** — grouped by `VATCategory.output_vat_account` (mirror of CDV's input-VAT buckets; raises if a VAT-bearing line's category has no output account)
- **Dr Creditable WHT Receivable** — `total_wt`, only if > 0
- **Dr Cash/Bank** — `total_amount`

Rounding residual absorbed into the first revenue line (as CDV absorbs into the first expense line). JE must balance or posting raises `ValueError` (same guard as CDV).

**AR application on post** — `_apply_ar_collections(crv)` (mirror of `_apply_ap_payments`):
```
for each ar_line:
    inv = SalesInvoice(ar_line.invoice_id)
    inv.amount_paid += ar_line.amount_applied
    inv.balance      = inv.total_amount − inv.amount_paid
    if inv.balance <= 0: inv.status = 'paid'
    elif inv.amount_paid > 0: inv.status = 'partially_paid'
```
**Validation at create/post:** each `amount_applied` must satisfy `0 < amount_applied ≤ inv.balance` (the invoice's current open balance); reject with a domain `ValueError` surfaced verbatim (per the genericize-flash-keep-ValueError rule).

**Void** — `_reverse_ar_collections(crv)` mirrors CDV's void reversal: subtract each `amount_applied` from `inv.amount_paid`, recompute balance, restore status (`posted` if no payments remain, else `partially_paid`); guard against negative `amount_paid`. The stored JE is reversed via the existing reversal helper pattern.

## Open-invoice picker

`GET /cash-receipts/open-invoices?customer_id=N` → JSON list of that customer's open invoices (`status in ('posted','partially_paid')`, `balance > 0`, current branch), each `{invoice_id, invoice_number, invoice_date, due_date, balance}` — mirror of CDV's open-bills endpoint. Feeds the AR-line picker in the create form (Choices.js, per the search-select pattern).

## Cash Receipts Journal (`/journals/cr`)

Activate the stubbed route in `app/journals/views.py` (remove the `under_development` redirect), mirroring `/journals/cd`:
- New `app/journals/cr_journal_data.py` with `build_columnar_cr(...)` + `build_cr_journal_xlsx(...)`, modeled on `cd_journal_data.py`.
- `_cr_journal_context(branch_id)` + `cr_journal()` / `cr_journal_export()` routes mirroring the CD equivalents.
- Templates `journals/cr_journal.html` (+ print) mirroring the CD journal templates.

## Ripple Effects (explicit map)

- **`app/__init__.py`:** add `cash_receipts` model imports + blueprint registration; **remove** `receipts` model import + `receipts_bp` registration.
- **`app/users/module_access.py`:** repoint the `collections` registry entry `endpoints` from `('receipts.',)` to `('cash_receipts.', 'journals.cr_journal')` (mirroring how `payments` maps to `cash_disbursements.` + `journals.cd_journal`).
- **`app/templates/base.html`:** the "Cash Receipts" sidebar link points to `cash_receipts.list_*` (gated by the existing `collections` permission); active-state matching mirrors the CDV link.
- **Legacy `receipts`:** blueprint + model retired. The `receipts` table is left in place (no destructive drop in the migration); a follow-up may drop it once confirmed empty. Files under `app/receipts/` are deleted.
- **Audit:** every create/post/void calls `log_create`/`log_update`/`log_delete` with the CRV reference (per the audit-in-CRUD rule).
- **Period guard:** posting validates `crv_date` against open accounting period (reuse `validate_transaction_date_with_flash`), as CDV does.
- **Buttons/labels:** in-form submit = **Save**/**Update**; list launch button = **+ Enter CRV** / "Enter Cash Receipt"; per the Enter-vs-Create convention.
- **Demo seed:** the AR-Aging demo script's simulated partial payments are unaffected; replacing them with real CRVs is a noted follow-up, not in scope.

## Testing

Mirror the CDV test suite:
- **Unit:** `calculate_totals` (AR + revenue − WHT), `CRVRevenueLine.calculate_amounts` VAT extraction, AR-application math, over-application rejection.
- **Integration:** create draft; post → balanced JE + invoice balance reduced + status flip; multi-invoice application; direct-revenue-only receipt; mixed receipt; void → JE reversed + invoice balance restored; over-application (`amount_applied > balance`) rejected; branch scoping; role gating (`collections` permission); open-invoices endpoint; CR journal renders + exports.
- **Audit assertions** after each write (per project rule).

## Error Handling

- Domain `ValueError`s (over-application, unbalanced JE, missing GL account, missing Output VAT account) surface verbatim to the user; only broad `except Exception` is genericized (per genericize-flash-keep-ValueError).
- Posting to a closed period is blocked at the view layer with a flash.
- All multi-row writes are transactional; failures roll back the whole receipt.

## Open Questions

None — the design is a faithful mirror of an existing, tested module; all shapes and accounting rules are pinned to the CDV implementation.
