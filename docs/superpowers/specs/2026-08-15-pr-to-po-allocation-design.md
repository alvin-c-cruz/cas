# Purchase Requisition -> Purchase Order: line-level allocation

**Date:** 2026-08-15
**Status:** Design approved, plan not yet written
**Module:** `purchase_requests`, `purchase_orders`

## Problem

A buyer cannot get requisitions into purchase orders in the shapes the work
actually takes.

Today the only path is a **Convert to Purchase Order** button on an approved
requisition's detail page. It creates one draft PO carrying every line, sets the
requisition to `converted`, and stops. Consumption is tracked at the header:
`PurchaseRequest.purchase_order_id`, `is_converted()`, and nothing anywhere
carries a `purchase_request_item_id`.

That forecloses three things the owner needs, all at once:

1. **Finding the work.** Nothing says "these requisitions are approved and
   awaiting a purchase order". The buyer must know to filter the requisition
   list.
2. **Combining.** Three departments raise requisitions naming the same supplier;
   the buyer wants one purchase order to that supplier, not three.
3. **Splitting.** A requisition lists parts from three suppliers, so it cannot
   become one purchase order at all. This is the shape PhilGen's spare-parts
   requisitions actually take.

All three dissolve into one feature: let the buyer pick individual requisition
**lines**, in partial quantities, from inside the purchase order they are
building. Combining is picking lines from several requisitions; splitting is
leaving lines behind for a second order; the picker is the worklist.

## Non-goals

- No vendor on the requisition. Settled 2026-08-14: the requestor states the
  need, purchasing chooses the supplier. Nothing here weakens that.
- No pricing on the requisition. Pulled lines arrive with product, description,
  quantity and unit of measure; **unit price stays blank** for the buyer.
- No worklist page in the purchase-orders module. The picker is the queue.
- No change to `app/amendments/`. The shared validator's existing hooks are
  enough (see "Amendment protection").

## Decisions

| Question | Decision |
|---|---|
| Granularity | Partial quantities per line, not whole lines |
| Entry point | A picker on the purchase-order form |
| Partly-ordered status | New `partially_converted` |
| Existing Convert button | Kept, as a whole-requisition shortcut |
| Tracking mechanism | Derived from PO lines; nothing stored |
| Over-ordering | Refused; the open quantity is the ceiling |
| Draft POs | Count against the requisition; reopen if cancelled |

### Why derived rather than a stored counter

CAS has tried both, and one is dead.

`PurchaseOrderItem.received_quantity` and `PurchaseOrderItem.billed_quantity`
are declared as columns and **never assigned anywhere in the application** --
the "guard reads a field nothing writes" pattern recorded in memory
`feedback-guard-reads-a-field-nothing-writes`. Meanwhile, in the same models
file, the receiving side derives its answer and works:

```python
def po_line_open_qty(po_item, exclude_rr_id=None):
    """Ordered qty minus qty already received by non-cancelled, non-draft RRs."""
    ordered = Decimal(str(po_item.quantity or 0))
    q = (db.session.query(db.func.coalesce(db.func.sum(ReceivingReportItem.received_quantity), 0))
         .join(ReceivingReport, ReceivingReportItem.receiving_report_id == ReceivingReport.id)
         .filter(ReceivingReportItem.purchase_order_item_id == po_item.id)
         .filter(ReceivingReport.status.in_(COMMITTED_STATUSES)))
    if exclude_rr_id is not None:
        q = q.filter(ReceivingReport.id != exclude_rr_id)
    return ordered - Decimal(str(q.scalar() or 0))
```

With partial quantities the hard part is not the picking -- it is keeping the
number honest when a PO is cancelled, voided, amended, or has a line deleted.
Deriving removes that entire class of bug: a cancelled PO's lines simply stop
matching the filter. No restore path exists to be forgotten.

## Data model

**One new column.** `PurchaseOrderItem.source_pr_item_id`, nullable `Integer`,
indexed. A bare Integer rather than a `ForeignKey`: SQLite batch `add_column`
raises `ValueError: Constraint must have a name` on an inline FK, and FK
enforcement is off app-wide. Precedent: `SalesOrder.quotation_id`, migration
`29500ade76f8`.

**One new module,** `app/purchase_requests/allocation.py`, shaped like
`app/purchase_billing.py` -- small, single-purpose, imported by both consumers.
`purchase_requests/views.py` is already 764 lines and both the picker route and
the shortcut need these:

```python
COMMITTED_PO = ('draft', 'approved', 'partially_received', 'closed')  # all but cancelled

def pr_line_open_qty(pr_item, exclude_po_id=None): ...
def open_lines_for_branch(branch_id, exclude_po_id=None): ...
def assert_within_open_qty(pr_item, qty, exclude_po_id=None): ...   # raises ValueError
def recompute_pr_status(pr): ...
```

`pr_line_open_qty` mirrors `po_line_open_qty` including the exclude argument.

**Nothing is stored.** No `ordered_quantity` on either side.
`PurchaseRequest.purchase_order_id` remains, written by the shortcut as a
back-link, but stops being the definition of consumption.

**Three stubs become real.** `PurchaseRequest.consumed_qty()` returns `0` today
and `has_any_child_reference()` returns `False`, above a comment reading "no
table carries a purchase_request_item_id". After this, one does. The shared
amendment validator already calls both hooks, so line-level amendment protection
arrives without touching `app/amendments/`.

**Migration:** one nullable Integer plus its index. No data migration -- existing
PO lines get `NULL`, meaning "not from a requisition", which is true.

## Components and data flow

**Endpoint:** `GET /purchase-requests/open-lines` returning JSON. On the source
module, matching `/purchase-orders/billable`, so the requisitions module's own
`before_request` gate 404s it when the module is off.

1. On a new or draft purchase order the buyer clicks **+ Pull from
   Requisitions**.
2. The form fetches `open-lines`, scoped to `session['selected_branch_id']`,
   requisitions in `approved` or `partially_converted`, with `exclude_po_id` set
   when editing.
3. A modal lists open lines grouped by requisition: PR Number, Date Needed /
   ASAP, item, unit, requested, already ordered, open, and a quantity box
   defaulting to the full open amount.
4. Ticked lines append to the existing line grid, carrying `source_pr_item_id`
   on the row's dataset, prefilled with product, description, quantity and unit.
   Unit price is left blank.
5. The submit serialiser -- which already walks `#lineItemsBody tr` and reads
   `tr.dataset` -- emits one more key, exactly as `po_item_id` works today.
6. `_assign_po_line_fields` reads `source_pr_item_id` and calls
   `assert_within_open_qty`.

**Date Needed / ASAP is shown in the picker.** It is the buyer's prioritisation
signal, and it is why that field was built first.

**The shortcut shares the tail.** `convert()` stops hand-building
`PurchaseOrderItem`s; it asks `open_lines_for_branch` for that one requisition's
open lines and runs them through the same apply path. One ceiling rule in one
place -- the discipline `_assign_po_line_fields` already keeps for its two line
paths.

## Status lifecycle

`approved -> partially_converted -> converted`, mirroring the purchase order's
own `approved -> partially_received -> closed`.

`recompute_pr_status(pr)` runs after any PO save, cancel or void touching
requisition-sourced lines. It is expressed over a per-line predicate rather than
over quantities, because an unquantified line has no arithmetic to compare:

> A line is **open** when it has remaining quantity, or -- if it carries no
> quantity at all -- when no committed PO line references it.

- every line open, none touched -> `approved`
- some open, some not -> `partially_converted`
- no line open -> `converted`

**This is recompute-from-source, not increment-and-decrement.** It is
idempotent and never reads its own previous value, so a status that somehow
disagrees with reality is repaired by running it again. A missed decrement in a
counter-based design would be permanent.

**`is_converted()` is redefined** to mean *fully* converted -- no line has open
quantity left. Its current form, `status == 'converted' or purchase_order_id is
not None`, breaks immediately, because the shortcut sets `purchase_order_id`
even on a partial pull.

**`AMEND_STATUSES` becomes `('approved', 'partially_converted')`.** With the
hooks implemented, the shared validator refuses to shrink or delete an
already-ordered line while still permitting untouched lines to change. Today a
converted requisition is frozen wholesale; after this it is frozen exactly where
it must be.

A **fully** `converted` requisition stays non-amendable, as it is today. Every
line is consumed, so the validator would refuse every edit except *adding* a new
line -- and a requisition that has already been fully ordered is the wrong place
to raise new demand. Raise a new requisition instead. This is a deliberate
carry-over of current behaviour, not an oversight.

**Five places enumerate statuses** and each needs the new member:
`VALID_PR_STATUSES`; the list page's `badge_map`, filter options and summary
cards; and the detail page's `status not in ['converted','cancelled','rejected']`
guard on Cancel. The `convert()` route's own `status != 'approved'` check must
also accept `partially_converted`, or the shortcut dies after the first partial
pull.

## Error handling and edge cases

**The ceiling is enforced at save, server-side, by re-deriving** -- not by the
modal's `max`, which a POST bypasses. Two buyers each seeing 20 open and each
pulling 20: the second save re-derives, sees the first buyer's line, and raises
`ValueError('Line 3: only 8 of Carbide remain unordered')`, routed through the
existing flash-and-re-render path that preserves typed lines.

**Self-collision.** Opening a draft PO that already pulled 20 and saving it
unchanged must succeed. That is `exclude_po_id`. This is the likeliest bug to
ship: the picker works, the first save works, and *editing* breaks.

**`source_pr_item_id` must survive both renders.** Draft edit rebuilds lines via
`_parse_and_attach_po_lines`, so a serialiser that drops the source id silently
orphans every pulled line and reopens the requisition. Same shape as the
`po_item_id` fallback the form already documents, and it gets the same
treatment: carried on the dataset, re-emitted on submit, asserted by the node
line-identity harness.

**Reopening is automatic.** Cancel a PO, void it, or delete a pulled line and
those lines stop matching `COMMITTED_PO`. Only `recompute_pr_status` need run.

**Unquantified lines.** A requisition line may have no quantity
(`LINE_QUANTITY_REQUIRED = False`, for "Cement, quantity to follow"). It has no
ceiling. It appears in the picker with an empty quantity box the buyer must
fill; `assert_within_open_qty` skips the arithmetic; the line counts as consumed
once any committed PO line references it. Boolean, not subtraction.

**Branch scoping is re-checked at save.** The picker filters by session branch;
a crafted POST could name another branch's line. Same class of hole as the
amendment applier's scoped lookup, which slice 2's review found live on the PO
side.

**Requisitions off means nothing changes.** No button, no route, and the save
path is a strict no-op when no source ids are posted -- the rule
`_bill_purchase_sources` already follows.

## Testing

**Unit** -- `pr_line_open_qty`: nothing ordered; partly ordered; fully ordered; a
cancelled PO does not count; `exclude_po_id` does not count itself; a
NULL-quantity line has no ceiling.

**Integration, the endpoint** -- branch scoping; the `approved` /
`partially_converted` filter; fully-ordered lines excluded; 404 when the module
is off.

**Integration, the rules** -- over-ordering refused with typed lines preserved;
branch mismatch refused on a crafted POST; unchanged draft-PO edit succeeds.

**Node line-identity harness** -- `source_pr_item_id` survives both renders. That
harness is the only thing that executes the form's real JS; on 2026-08-14 it
caught both the ASAP toggle breaking and the UoM serialiser omission.

**Status recompute** -- including idempotence, and reopening after cancel, void
and line removal.

**Amendment protection** -- shrinking an ordered line refused; an untouched line
on the same requisition still amendable. The second is the control, and it is
what proves the guard is conditional rather than a blanket freeze.

### Mutations to name in the implementation brief

Naming them up front is what makes an implementer find their own vacuous tests.

1. Drop `exclude_po_id` from the open-qty query -> the draft-edit test must fail.
2. Remove `source_pr_item_id` from the serialiser -> the harness test must fail.
3. Make `assert_within_open_qty` always pass -> the over-order test must fail.
4. Add `'cancelled'` to `COMMITTED_PO` -> the reopen test must fail.

### Gates beyond pytest

- The migration runs against a **copy of the real PhilGen database**, not a
  conftest `create_all()`. Both migrations shipped on 2026-08-14 were verified
  this way.
- This touches templates and JS, so a **browser pass on the branch is blocking**.
  The Chrome extension was disconnected as of 2026-08-15; if it still is at
  implementation time, the branch cannot merge on pytest-only evidence.

## Deployment note

PhilGen's live instance is behind by the migrations already on `main`
(`prdate_0001`, `prdate_0002`) and would gain a third from this work. Angilyn
sees none of it until a deploy.
