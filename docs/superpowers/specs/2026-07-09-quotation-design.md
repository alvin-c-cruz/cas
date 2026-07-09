# Quotation (R-01) — Design

**Date:** 2026-07-09 · **Roadmap:** R-01 Sales (Order-to-Cash), slice "Quotations" · **Status:** proposed

## Goal

A **Quotation** — the front of the order-to-cash chain (**Quotation → SO → DR → SI**). A pre-sale,
product-priced offer to a customer with a validity period; when the customer **accepts**, it creates a
linked **draft Sales Order** carrying the quote's lines, customer, terms, and salesperson.

## Scope boundary

- **This spec:** the Quotation document — create, product-priced lines, draft→sent→accepted/rejected/
  cancelled lifecycle with a `valid_until` (derived expiry), **accept → create-linked-SO**, standard
  print, module gating, numbering, salesperson.
- **Out of scope:** a "revise/clone a sent quote" convenience (deferred), the pre-printed quotation
  layout designer (deferred), any accounting (a quote posts nothing — like the SO).

## Locked decisions

1. **Accept → creates an SO.** Marking a *sent* quote **accepted** generates a **draft SO** with the
   quote's lines copied, links both ways, and carries customer/terms/salesperson forward.
2. **Lifecycle:** `draft → sent → accepted | rejected | cancelled`.
   - **`valid_until`** date on every quote; **expiry is DERIVED** — a still-`sent` quote past
     `valid_until` **displays** as "Expired" and **cannot be accepted** (no stored `expired` status, no
     scheduled sweep).
   - **Lock at sent** — draft is the only editable state.
   - `rejected` / `cancelled` carry a reason; both terminal.
3. **Line shape:** own `QuotationItem`, same product-based VAT-inclusive lines as `SalesOrderItem`
   (product · qty · unit_price · uom · vat_category → amount).
4. **Summary:** customer-facing **breakdown — Subtotal / VAT / Total** (a quotation is a price offer),
   computed per the quote's **VAT treatment** (below).
10. **VAT treatment (header-level `vat_treatment` ∈ {`inclusive`, `exclusive`, `zero_rated`}, default
    `inclusive`)** — chosen per quotation; drives the summary math + print. **Quotation-only** — SO/SI
    stay VAT-inclusive. Formulas:
    - **inclusive:** line amounts are gross (incl. 12%); Total = Σ lines; VAT extracted; Net = Total − VAT.
    - **exclusive:** line amounts are net; Net = Σ lines; VAT = Net × 12%; **Total = Net + VAT**.
    - **zero_rated:** VAT = 0; Total = Net = Σ lines.
    On **accept → SO**, translate to the SO's inclusive convention: *exclusive* folds 12% into each
    `unit_price` (SO lines become inclusive); *zero_rated* sets the SO lines' `vat_category` to a
    zero-rate category; *inclusive* copies as-is. The created SO is always VAT-inclusive.
5. **Chain link (model change):** nullable **`quotation_id` FK on `SalesOrder`** + nullable
   `sales_order_id` FK on the quote.
6. **Module:** new `quotations` — `optional`, `depends_on: ['sales_orders']`, `per_user`, default-off,
   branch-scoped.
7. **Numbering:** `QTN-YYYY-MM-####` per branch/month.
8. **Print:** standard printable quotation now; pre-printed designer deferred.
9. **Salesperson:** on the quote (Employees-module-gated picker), copied to the SO on accept via
   `copy_salesperson`.

## Status lifecycle

| Status | Editable? | Notes |
|---|---|---|
| **draft** | yes | being prepared |
| **sent** | **locked** | issued to customer; `valid_until` in force; acceptable until expiry |
| **accepted** | locked | **creates the draft SO** + links; terminal |
| **rejected** | locked | reason; terminal |
| **cancelled** | locked | reason; terminal |
| *Expired* (derived) | — | `status=='sent' and valid_until < today` → shown "Expired", **accept refused** |

## Architecture / components

New blueprint `app/quotations/` mirroring the `sales_orders` package.

### Models (`app/quotations/models.py`)
- **`Quotation`** (header): `id`, `quotation_number` (unique `QTN-YYYY-MM-####`, indexed), `branch_id`,
  `quotation_date` (Date), `valid_until` (Date), customer snapshot (`customer_id`, `customer_name`,
  `customer_tin`, `customer_address`), `payment_terms`, `reference`, `notes`, `status` (default
  `'draft'`, indexed), **`vat_treatment` (String(10), default `'inclusive'` — inclusive/exclusive/
  zero_rated)**, `salesperson_id` (nullable FK employees) + relationship, `sales_order_id`
  (nullable FK sales_orders — the SO created on accept), `subtotal`/`vat_amount`/`total_amount`
  (Numeric), audit (`created_by_id`/`created_at`/`updated_at`; `sent_by_id`/`sent_at`;
  `accepted_by_id`/`accepted_at`; `rejected_by_id`/`rejected_at`/`reject_reason`;
  `cancelled_by_id`/`cancelled_at`/`cancel_reason`), `line_items` (cascade delete-orphan).
  - `calculate_totals()` — branches on `vat_treatment`: **inclusive** → `subtotal`=Σ line amounts,
    `vat_amount`=Σ extracted VAT, `total`=subtotal; **exclusive** → `subtotal`(net)=Σ line amounts,
    `vat_amount`=subtotal×12%, `total`=subtotal+vat_amount; **zero_rated** → `vat_amount`=0,
    `total`=`subtotal`=Σ line amounts. (VAT rate from the line/SalesVATCategory; 12% shown as the
    standard rate.)
  - `is_expired` property — `self.status == 'sent' and self.valid_until and self.valid_until < ph_now().date()`.
  - `to_dict()` incl. `status`, `salesperson_name`, `sales_order_number`, `is_expired`.
- **`QuotationItem`** — a verbatim structural clone of `SalesOrderItem` (product_id, quantity,
  unit_price, uom_text/unit_of_measure_id, amount, vat_category, vat_rate, line_total, vat_amount,
  `calculate_amounts()`, `to_dict()`), FK `quotation_id`.

### Model change (`app/sales_orders/models.py`)
- Add `quotation_id = db.Column(db.Integer, db.ForeignKey('quotations.id'), nullable=True, index=True)`
  to `SalesOrder` + relationship. (Vestigial-safe; existing SOs keep it null.)

### Accept → SO (`app/quotations/views.py::accept`)
- Guard: the quote must be `sent` and **not expired** (`is_expired` False), else refuse.
- Build a `SalesOrder(status='draft', branch_id, customer snapshot, payment_terms, quotation_id=quote.id)`,
  `copy_salesperson(quote, so)`, then for each `QuotationItem` append a `SalesOrderItem` copying
  product/qty/uom, **translating unit_price/vat by the quote's `vat_treatment`** so the SO is
  VAT-inclusive: *inclusive* → copy `unit_price`/`vat_category` as-is; *exclusive* → `unit_price =
  net_unit_price × 1.12` (fold VAT in) + keep the standard vat_category; *zero_rated* → copy price +
  set `vat_category` to a zero-rate SalesVATCategory. Then `so.calculate_totals()`. Commit.
- Set `quote.status='accepted'`, `quote.accepted_by_id/at`, `quote.sales_order_id = so.id`. Audit both.
- Flash + redirect to the new SO (so the user lands on the created order).

### Views (`app/quotations/views.py`)
- `list` (branch-scoped, status/customer/date filters — "Expired" as a derived filter), `create`
  (customer picker + product line grid, mirror the SO form), `edit` (draft only), `view`/detail,
  `print`, and transitions: `send` (draft→sent), `accept` (above), `reject` (sent→rejected, reason),
  `cancel` (reason). Role gate: create/edit/send by staff/accountant/admin; accept/reject/cancel by
  accountant/admin. `generate_quotation_number(branch_id)` → `QTN-YYYY-MM-####`.

### Forms / templates
- `QuotationForm` (customer_id, quotation_date, valid_until, **`vat_treatment` SelectField
  (inclusive/exclusive/zero_rated)**, salesperson_id, payment_terms, reference, notes; hidden `lines`
  JSON), mirroring `SalesOrderForm`.
- `list.html`, `form.html` (product line grid like SO's), `detail.html` (header + lines + Subtotal/VAT/
  Total summary + status-gated Send/Accept/Reject/Cancel actions via custom HTML modals — no JS
  popups), `print.html` (self-contained quotation: header + validity + lines + Subtotal/VAT/Total).
  Bare numbers, currency named once in prose. `qty_fmt` filter for quantities.

### Module registry + nav + migration
- `module_access.py`: `{'key':'quotations','label':'Quotations','section':'Transactions','area':'Sales',
  'group':'Documents','optional':True,'depends_on':['sales_orders'],'default_enabled':False,
  'per_user':True,'endpoints':('quotations.',)}`.
- `base.html` nav link (gated); blueprint + models registered in `create_app`.
- One hand-written batch migration: create `quotations` + `quotation_items`, **and** add
  `quotation_id` to `sales_orders` (`op.batch_alter_table('sales_orders')`). Verify on a copy of `cas.db`.

## Testing (TDD)

- **Model:** quotation + item construct; **`calculate_totals` for all three `vat_treatment`s** — same
  net produces inclusive (VAT extracted, total=subtotal), exclusive (VAT added, total=net+vat), and
  zero_rated (vat=0, total=net); `is_expired` true only when sent+past; `to_dict`.
- **Accept translation:** an *exclusive* quote → SO lines are VAT-inclusive (unit_price folded ×1.12);
  a *zero_rated* quote → SO lines carry a zero-rate vat_category; an *inclusive* quote → copied as-is;
  each resulting SO's totals tie.
- **Lifecycle:** draft→sent locks (edit refused); a sent quote past `valid_until` → `is_expired`,
  **accept refused**; reject/cancel need a reason.
- **Accept → SO (the core):** accepting a sent quote **creates a draft SO** whose lines match the
  quote's (product/qty/price), `SO.quotation_id == quote.id`, `quote.sales_order_id == so.id`,
  salesperson carried; quote status `accepted`; totals tie.
- **Numbering / module gating / salesperson-gated-picker / print-no-peso** — as for SO.
- **Audit:** each transition logs a `quotations` audit row.

## Blast radius

New blueprint `app/quotations/` (+ templates); one migration (2 new tables + `sales_orders.quotation_id`);
`module_access.py` + `base.html` + `create_app` registration; `regression-map.json` (new `quotations`
module). Reuses `copy_salesperson`, `SalesOrder`/`SalesOrderItem`, cache helpers, `qty_fmt`.

**⚠️ Build-time migration-fork coordination:** the in-flight Delivery Receipt branch *also* adds a
migration off the same `main` head. If both merge independently, Alembic gets **two heads** again
(the exact deploy-blocker we just fixed). **Mitigation:** merge one first, then rebase the second's
`down_revision` onto the new head (or add a `flask db merge`), and verify a single head before push.

## Out of scope

- Revise/clone a sent quote (versioning) — deferred.
- Pre-printed quotation layout designer — deferred.
- Any journal entry / accounting — a quote posts nothing.
- The DR→SI billing flow and the Approver role (separate specs).
