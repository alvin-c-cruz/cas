# Order Monitoring Dashboard — Design

**Date:** 2026-07-08 · **Roadmap:** R-01 Sales (Order-to-Cash), slice #8 · **Status:** proposed

## Goal

A read-only, **count-based** dashboard that lets sales/ops staff monitor the open-order book at a
glance: how many orders are open, drafted, overdue for delivery, or due soon — plus a status and
aging breakdown and the busiest customers. **No monetary values are shown anywhere** (per the
no-currency-symbol direction and an explicit "do not show the peso value" instruction).

## Rationale & scope boundary

The Sales Order lifecycle today is `draft → confirmed → cancelled`; there is **no delivered/billed
status yet** (that arrives with the SO→DR→SI chain linkage, later R-01 slices). So this v1 keys off
what exists — `status`, `order_date`, `expected_delivery_date`, `customer_name` — and gains
delivered/billed columns later, non-breakingly. It is purely a **read-over** of existing data: **no
new columns, no migration.**

## Placement, gating, scoping

- **Route:** `GET /sales-orders/monitor` in the existing `sales_orders` blueprint (endpoint
  `sales_orders.monitor`). The `sales_orders` registry entry already covers the `sales_orders.`
  endpoint prefix, so the module gate (and the branch `before_request` guard) apply with no registry
  change — the page is reachable exactly when the Sales Orders module is enabled.
- **Entry point:** a prominent **"Order Monitoring" link** on the Sales Orders list header (next to
  "Enter Sales Order"). A standalone Sales→Reports **sidebar item is deferred**: the registry's
  `depends_on` is enforced only at toggle time, so a separate registry entry would not auto-hide when
  `sales_orders` is off, and adding a render-time dependency check would regress the
  "SO enabled without products" test pattern. Linking from the (already-gated) SO list is the clean,
  correct v1. *(If the user prefers a sidebar item, that becomes a small follow-up once render-time
  dependency gating exists.)*
- **Branch-scoped:** every metric is computed for `session['selected_branch_id']` only, matching the
  SO list and the rest of the app.

## Metrics

**Four count cards:**
- **Open** — `status == 'confirmed'`
- **Drafts** — `status == 'draft'`
- **Overdue delivery** — `confirmed` AND `expected_delivery_date` is set AND `< today`
- **Due soon** — `confirmed` AND `today <= expected_delivery_date <= today + 7 days`

**Three breakdowns:**
- **By status** — Chart.js **donut**: Draft / Confirmed / Cancelled counts.
- **Aging of open orders** — Chart.js **bar**: confirmed orders bucketed by `(today - order_date).days`
  into `0–7 / 8–30 / 31–60 / 60+`.
- **Top customers by open-order count** — a small table: top 5 `customer_name` by count of `confirmed`
  orders, descending.

**Definitions (locked):** *Open = confirmed only* (drafts counted separately); *cancelled* is excluded
from all open/overdue/due-soon/aging metrics and appears only in the by-status donut; an order with a
null `expected_delivery_date` is never overdue/due-soon.

## Architecture

Mirrors the existing `app/dashboard/dashboard_data.py` + Chart.js pattern (Chart.js is already bundled
locally at `app/static/chart.umd.min.js`; the CSP forbids CDNs).

- **`app/sales_orders/monitoring.py`** — one pure function:
  ```python
  def get_order_monitoring(branch_id, today):
      """Count-based order-monitoring metrics for one branch, as of `today` (a date).
      Returns a plain dict (no ORM objects) — safe to hand straight to the template.
      """
      # -> {
      #   'cards':        {'open': int, 'drafts': int, 'overdue': int, 'due_soon': int},
      #   'by_status':    {'labels': ['Draft','Confirmed','Cancelled'], 'data': [int,int,int]},
      #   'aging':        {'labels': ['0-7','8-30','31-60','60+'], 'data': [int,int,int,int]},
      #   'top_customers':[{'customer_name': str, 'count': int}, ...],  # <=5, desc
      # }
  ```
  `today` is a parameter (injected by the view as `ph_now().date()`) so unit tests are deterministic.
  The function issues a handful of branch-scoped `SalesOrder` count queries — no ORM objects escape.
- **View `sales_orders.monitor`** — resolves the branch (reuse the existing branch-in-session guard),
  calls `get_order_monitoring`, renders `monitoring.html`.
- **Template `monitoring.html`** — the 4 cards, two `<canvas>` charts initialised from the dict
  (same `<script src=chart.umd.min.js>` include and init style as `dashboard/index.html`), and the
  top-customers table. Bare integers only; no currency.
- **Drill-through:** each card links to the SO list filtered to its slice —
  `Open → ?status=confirmed`, `Drafts → ?status=draft`, `Overdue → ?status=confirmed&overdue=1`,
  `Due soon → ?status=confirmed&due_soon=1`. This requires **two new optional filters on the SO list
  view** (`overdue=1`, `due_soon=1`), applied only when present so existing list behaviour is
  unchanged.

## Testing

- **Unit (`test_order_monitoring.py`):** seed SOs across statuses and a spread of `order_date` /
  `expected_delivery_date`, call `get_order_monitoring(branch, today=<fixed date>)`, and assert every
  card count, each aging bucket, the by-status triple, and the top-customer ordering. Include a
  **second branch** whose orders must be excluded (branch isolation).
- **Integration:** `GET /sales-orders/monitor` → 200 with SO enabled + a branch selected; the four
  card labels and both `<canvas>` ids render; the page is **blocked/redirected when the sales_orders
  module is disabled**. Assert **no peso glyph** in the response.

## Blast radius

- New files: `app/sales_orders/monitoring.py`, `app/sales_orders/templates/sales_orders/monitoring.html`,
  a new view + route.
- `app/sales_orders/views.py` list view: two additive optional filters (`overdue`, `due_soon`).
- `app/sales_orders/templates/sales_orders/list.html`: the "Order Monitoring" header link.
- `.claude/regression-map.json`: fold the new files under the `journal_entries`-style `sales_orders`
  coverage (add `monitoring.py` to blast radius if needed).

## Out of scope (v1)

Delivered/billed status and columns (needs the SO→DR→SI linkage — dashboard gains these later),
**any monetary value**, export/print, auto-refresh, per-user configuration, a standalone sidebar item.
