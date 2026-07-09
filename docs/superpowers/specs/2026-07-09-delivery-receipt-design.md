# Delivery Receipt (R-01) — Design

**Date:** 2026-07-09 · **Roadmap:** R-01 Sales (Order-to-Cash), slice "Delivery Receipt" · **Status:** proposed

## Goal

A **Delivery Receipt (DR)** that records what is physically delivered against a Sales Order — the
connective middle link of the **SO → DR → SI** chain (deliver against the order, then bill against
the delivery). It is **operational-only** (no journal entry). Partial deliveries are first-class: one
SO can be fulfilled by many DRs, which is what later lets one SI bill many DRs.

## Scope boundary (this spec = the DR document module only)

- **This spec:** the DR document — create-against-SO, delivered-quantity tracking with a guard,
  status lifecycle, printable DR, module gating, numbering, salesperson carry.
- **Sub-project #2 (separate spec):** the **DR → SI billing flow** — creating an SI from
  delivered-but-unbilled DRs (1 SI ← many DRs). This spec only lays the *seam* (a `billed` status +
  nullable `sales_invoice_id` FK on the DR).
- **Prerequisite (separate spec):** the **Approver role** — an app-wide, approve-only maker-checker
  role that gates the DR `draft → approved` transition (and SI / earlier documents). Being brainstormed
  separately. **Sequencing:** if the DR module is built before the Approver role exists, interim-gate
  `approve` to admin/accountant and swap in the Approver role when it lands.
- **Deferred to R-03:** the on-delivery inventory-relief / COGS journal entry. This spec reserves an
  inert posting seam (`post_delivery_je(dr)`) for it; nothing posts now.

## Locked decisions

1. **Operational-only, no JE** — SI stays the sole BIR/output-VAT posting document. An inert
   `post_delivery_je(dr)` helper is the seam R-03 will fill; it is a no-op now.
2. **1 SO → many DRs; a DR always references an SO** (never standalone). Each DR line points at a
   specific SO line and records a **delivered quantity**, guarded so cumulative delivered across all
   non-cancelled DRs for that SO line **≤ the SO line's ordered quantity**.
3. **Billing seam:** the DR carries a nullable `sales_invoice_id` FK + a `billed` status. The current
   1:1 `SalesOrder.sales_invoice_id` becomes vestigial (SO is billed indirectly via its DRs) — left in
   place, unused, cleaned up later if desired.
4. **Lifecycle:** `draft → approved → delivered → billed`, plus `cancelled`.
5. **Module:** new `delivery_receipts` — `optional`, `depends_on: ['sales_orders']`, `per_user`,
   default-off, branch-scoped.
6. **Numbering:** system-generated `DR-YYYY-MM-####` per branch/month.
7. **Print:** standard self-contained printable DR now; pre-printed drag-designer deferred.
8. **Salesperson:** carried from the SO via `copy_salesperson`, editable on the DR, gated on the
   Employees module.

## Status lifecycle (semantics)

| Status | Editable? | Delivered qty counts toward the SO guard? | Notes |
|---|---|---|---|
| **draft** | yes | **no** (provisional) | freely edited by staff+ |
| **approved** | **locked** | **yes** (commits, guarded ≤ SO open qty) | transition gated to the **Approver** role (+ admin); billable-eligible |
| **delivered** | locked | yes | stamps physical dispatch (`delivered_by`, `delivered_at`); no qty change |
| **billed** | locked | yes | set by the DR→SI flow (sub-project #2); read-only here |
| **cancelled** | locked | **no** (released) | allowed from draft/approved/delivered (not billed); requires a reason; releases committed qty |

- **Lock at approved** (draft is the only editable state). To change an approved/delivered DR, cancel
  it (releasing its quantities) and enter a new one.
- **Commit at approved** — the guard is enforced at the `draft → approved` transition; draft DRs do
  not consume SO open quantity.

## Architecture / components

New blueprint `app/delivery_receipts/` (models · forms · views · templates), mirroring the
`sales_orders` package shape.

### Models (`app/delivery_receipts/models.py`)
- **`DeliveryReceipt`** (header):
  - `id`, `dr_number` (unique, `DR-YYYY-MM-####`, indexed), `branch_id` (FK branches, indexed).
  - `sales_order_id` (FK sales_orders, **NOT NULL**, indexed) + `sales_order` relationship.
  - Customer snapshot **derived from the SO** at create: `customer_id`, `customer_name` (no customer
    picker — inherited from the chosen SO).
  - `delivery_date` (Date).
  - `status` (String, default `'draft'`, indexed) — one of the five above.
  - `salesperson_id` (nullable FK employees) + relationship (carried from SO).
  - `sales_invoice_id` (nullable FK sales_invoices, indexed) — the **billing seam**.
  - `remarks` / `reference` (optional text).
  - Audit: `created_by_id`, `created_at`; `approved_by_id`/`approved_at`; `delivered_by_id`/`delivered_at`;
    `cancelled_by_id`/`cancelled_at`/`cancel_reason`.
  - `to_dict()` incl. `salesperson_name`, `status`, `sales_order` number.
  - `line_items` relationship (cascade delete-orphan, ordered by line_number).
- **`DeliveryReceiptItem`** (line):
  - `id`, `delivery_receipt_id` (FK, NOT NULL, indexed), `line_number`.
  - `sales_order_item_id` (FK sales_order_items, **NOT NULL**) + relationship — the DR line *is* a
    delivery against a specific SO line; **product / uom / unit_price are read through this
    relationship** (no duplication — SO lines are frozen once the SO is confirmed, so the reference is
    stable). A light `product_id` snapshot is kept only for print robustness.
  - `delivered_quantity` (Numeric(15,4), NOT NULL).
  - `to_dict()` exposes `product_code`/`product_name`/`uom`/`unit_price` (read from the SO line) +
    `delivered_quantity` + the SO line's `ordered_quantity` and computed `open_quantity`.

### Open-quantity + the guard (`app/delivery_receipts/models.py` or a small service)
- **`so_line_open_qty(sales_order_item)`** = `ordered_qty − Σ delivered_quantity` over all DR lines
  referencing that SO line whose DR status ∈ {approved, delivered, billed} (i.e. committed,
  non-cancelled, non-draft).
- **Guard at approve:** for each DR line, `(committed_so_far_excluding_this_DR + this line's
  delivered_quantity) ≤ ordered_qty`, else raise `ValueError('Line N: delivering X exceeds the open
  quantity Y for <product>.')` — flashed verbatim; the approve is refused and the DR stays draft.
  (Also validated at draft-save as a soft check, but the *binding* enforcement is at approve, per
  "commit at approved".)

### Posting seam
- `post_delivery_je(dr)` in the models/service module — **currently a no-op** returning `None`
  (documented as the R-03 inventory-relief/COGS hook). Not called by any transition yet.

### Views (`app/delivery_receipts/views.py`)
- `list` (branch-scoped, status/SO/customer/date filters), `create` (GET: pick a confirmed,
  not-fully-delivered SO → form pre-loads its lines with each line's open qty; POST: persist draft +
  carry salesperson), `edit` (draft only), `view`/detail, `print` (standard printable DR),
  and the transitions: `approve` (guarded; Approver+admin), `mark_delivered`, `cancel` (reason).
- Role gate: draft create/edit by staff/accountant/admin; **approve by the Approver role (+ admin)**;
  deliver by staff+ ; cancel by accountant/admin.
- `generate_dr_number(branch_id)` → `DR-YYYY-MM-####` (mirror `generate_so_number`).

### Forms (`app/delivery_receipts/forms.py`)
- `DeliveryReceiptForm`: `sales_order_id` (select of eligible SOs), `delivery_date`, `salesperson_id`
  (gated), `remarks`; line quantities submitted as a hidden JSON blob (mirror the SO line grid), each
  line = `{sales_order_item_id, delivered_quantity}`.

### Templates
- `list.html`, `form.html` (SO picker → line grid showing product · ordered · already-delivered ·
  **open** · *deliver-now qty* input · uom), `detail.html`, `print.html` (self-contained delivery
  document: header + customer + line table of product/qty-delivered/uom; **no amounts required** —
  a delivery doc; prices optional). No pre-printed designer this spec.

### Module registry + nav
- `app/users/module_access.py`: add `{'key':'delivery_receipts', 'label':'Delivery Receipts',
  'section':'Transactions', 'area':'Sales', 'group':'Documents', 'optional':True,
  'depends_on':['sales_orders'], 'default_enabled':False, 'per_user':True,
  'endpoints':('delivery_receipts.',)}`.
- `base.html`: nav link under Sales → Documents (gated).
- A **"Create Delivery Receipt"** action on a confirmed, not-fully-delivered SO's detail page.

### Migration
- One hand-written batch migration creating `delivery_receipts` + `delivery_receipt_items`
  (`op.create_table`). Verify on a copy of `cas.db`. No change to existing tables.

## Testing (TDD)

- **Model:** DR + item construct; `to_dict` carries salesperson/status/SO#; `line_items` cascade.
- **Open-qty / guard (the core):** two DRs partially delivering one SO line — cumulative ≤ ordered
  passes; a third that would exceed is **rejected at approve** (stays draft, flash); a **draft** DR
  does **not** consume open qty; **cancelling** an approved DR **releases** its qty back.
- **Lifecycle:** `draft→approved` gated (Approver/admin only — a plain staff user is refused);
  approved is **locked** (edit refused); `mark_delivered` stamps `delivered_by/at`; `cancel` requires a
  reason and releases qty; `billed` is not settable here.
- **Numbering:** `DR-YYYY-MM-####` increments per branch/month.
- **Module gating:** route blocked when `delivery_receipts` disabled; visible when enabled (which
  requires SO+Products+UoM on).
- **Salesperson:** create-from-SO carries `SO.salesperson_id`; editable; gated on Employees module.
- **Print:** renders the delivered lines; no peso glyph.
- **Audit:** each transition logs an audit row (module `delivery_receipts`).

## Blast radius

New blueprint `app/delivery_receipts/` (+ templates); one migration (2 new tables, no existing-table
change); `module_access.py` (registry) + `base.html` (nav) + SO detail (create-DR action);
`regression-map.json` (new `delivery_receipts` module + blast edges). Reuses `copy_salesperson`,
`get_active_*` cache helpers, the `qty_fmt` filter. `SalesOrder.sales_invoice_id` untouched (vestigial).

## Out of scope (this spec)

- DR → SI billing flow (create SI from DRs, `billed` transition) — **sub-project #2**.
- The Approver role's own definition — **separate spec** (this spec only *consumes* it).
- On-delivery COGS/inventory JE — **R-03** (seam reserved).
- Pre-printed DR layout designer — **follow-up** (standard print only now).
- Deriving an SO "fully-delivered/closed" fulfilment status + Order-Monitoring fulfilment columns —
  **follow-on** (Order Monitoring already reads SO status; enriched once the chain lands).
