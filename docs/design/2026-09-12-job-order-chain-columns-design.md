# Job Order Slips: document-chain columns — design

**Date:** 2026-09-12 · **Owner decision:** upgrade the Job Order Slips page in place;
chain columns only (no cards, no filters, no amounts).

**Amendment, same day:** the **CR # column was dropped** — collection is money, and the
slips page is unpriced. The chain shown is SO → DR → SI. The order's line items are
listed under each order row (quantity, description, delivery date; no price).

## Why

The Purchase Requests list answers "where have this requisition's goods got to?" with
four document-chain columns (`PO # · RR # · AP # · CD #`), resolved once per page from
the line links, committed documents only, several per cell when the requisition was
split. The owner wants the same answer on the sell side: from the Job Order Slips
page (the operations list of Sales Orders), which Delivery Receipts, Sales Invoices
and Cash Receipts exist for each order.

## What changes

`/sales-orders/job-order-slips` gains three columns between **Status** and
**Actions**: `DR # · SI # · CR #`. Each cell is a comma-separated list of links to
the documents, or an em dash when none exist — an em dash, not a blank, so an
undelivered row reads as answered rather than as a rendering gap.

Everything else about the page stays: the draft rule (`job_order_slips_show_drafts`),
the ordering, the Print action, and — deliberately — **no pricing columns**. SI and CR
are money documents; only their numbers appear.

## Links

| Column | Walk | Counts when |
|---|---|---|
| DR # | `delivery_receipts.sales_order_id` | DR status in `COMMITTED_STATUSES` (approved, delivered, billed). A draft DR has delivered nothing. |
| SI # | DR (as above) → `delivery_receipts.sales_invoice_id` | The link exists. It is set when the DR is billed and cleared when the SI is voided or cancelled (`_unbill_drs`), so the link itself is the truth; no SI status filter. |
| CR # | SI (as above) → `crv_ar_lines.invoice_id` → `cash_receipt_vouchers` | CRV status not in (voided, cancelled). A voided receipt collected nothing. |

Ordered by document number ascending; de-duplicated per SO (one SI billing two DRs of
the same order shows once; one CRV settling two SIs shows once).

## Code

- **New** `app/sales_orders/chain_links.py`: `dr_links_for_so_ids(so_ids)`,
  `si_links_for_so_ids(so_ids)`, `cr_links_for_so_ids(so_ids)`, each returning
  `{so_id: [(doc_id, number), ...]}` in ONE query for the whole list, plus the same
  `_dedup_links` shape as `purchase_requests/allocation.py`. Empty or `None` ids → `{}`.
  Never a per-row property on `SalesOrder`: the list is the reason the PR code rejected
  N+1.
- **Changed** `sales_orders/views.py::job_order_list()`: resolve the three dicts for
  the listed orders' ids and pass `dr_links`, `si_links`, `cr_links`.
- **Changed** `sales_orders/templates/sales_orders/job_order_list.html`: three `<th>`
  and three `<td>` copied from the PR list's cells, with the "resolved once per page,
  never query per row" comment.

## Tests (TDD, real documents, no mocks)

Unit (`tests/unit/test_so_chain_links.py`):
- DR: committed DR listed; draft DR not; two DRs both listed in number order; `[]`/`None` → `{}`.
- SI: listed once the DR is billed; absent after the SI is voided (link cleared); one SI across two DRs listed once.
- CR: listed when posted against the SI; absent when voided; one CRV across two SIs listed once.

Integration (`tests/integration/test_job_order_chain_columns.py`), via the real route:
- An SO with delivered DR + posted SI + posted CRV renders all three links.
- An SO with nothing renders `—` in all three cells.
- No amount from the SI or CRV appears in the SO's row (assert on the row, not the page).
- Header order: `Status · DR # · SI # · CR # · Actions`.

## Out of scope

Summary cards, filters, amounts, production documents, and `/sales-orders/monitor`.
