"""How much of a requisition line is already on order.

DERIVED, never stored. The answer is always a SUM over the purchase-order lines
that point at the requisition line, so cancelling or voiding a PO reopens its
lines with no restore step to forget.

This mirrors receiving_reports.models.po_line_open_qty deliberately. The stored
alternative already exists in this codebase and is dead:
PurchaseOrderItem.received_quantity and .billed_quantity are declared columns
that nothing ever assigns.
"""
from decimal import Decimal

from app import db

#: Every PO status except 'cancelled'. Draft counts on purpose -- a line pulled
#: onto a draft is spoken for, so two buyers cannot both claim it.
COMMITTED_PO = ('draft', 'approved', 'partially_received', 'closed')


def pr_line_ordered_qty(pr_item, exclude_po_id=None):
    """Total quantity committed PO lines have ordered against *pr_item*.

    Pass *exclude_po_id* to leave one purchase order out of the sum -- the draft
    being edited must not count its own lines against itself.
    """
    from app.purchase_orders.models import PurchaseOrder, PurchaseOrderItem
    q = (db.session.query(db.func.coalesce(db.func.sum(PurchaseOrderItem.quantity), 0))
         .join(PurchaseOrder, PurchaseOrderItem.purchase_order_id == PurchaseOrder.id)
         .filter(PurchaseOrderItem.source_pr_item_id == pr_item.id)
         .filter(PurchaseOrder.status.in_(COMMITTED_PO)))
    if exclude_po_id is not None:
        q = q.filter(PurchaseOrder.id != exclude_po_id)
    return Decimal(str(q.scalar() or 0))


def pr_line_open_qty(pr_item, exclude_po_id=None):
    """Requested minus ordered, or None when the line carries no quantity.

    None is not "zero open" -- it means there is no ceiling to enforce. A
    requisition line may legitimately have no quantity
    (PurchaseRequest.LINE_QUANTITY_REQUIRED is False).
    """
    if pr_item.quantity is None:
        return None
    return Decimal(str(pr_item.quantity)) - pr_line_ordered_qty(pr_item, exclude_po_id)


def pr_line_is_open(pr_item, exclude_po_id=None):
    """True when the line still needs ordering.

    The status rules are written over THIS, not over quantities, because a
    quantity comparison says nothing about an unquantified line. For those the
    test is boolean: open until any committed PO line references it.
    """
    if pr_item.quantity is None:
        return pr_line_ordered_qty(pr_item, exclude_po_id) == Decimal('0') and \
            not _has_committed_reference(pr_item, exclude_po_id)
    return pr_line_open_qty(pr_item, exclude_po_id) > Decimal('0')


def _has_committed_reference(pr_item, exclude_po_id=None):
    """Whether ANY committed PO line points at this requisition line.

    Separate from the quantity sum because a PO line may reference an
    unquantified requisition line while itself carrying a quantity of zero or
    None, which would sum to nothing and read as untouched.
    """
    from app.purchase_orders.models import PurchaseOrder, PurchaseOrderItem
    q = (db.session.query(PurchaseOrderItem.id)
         .join(PurchaseOrder, PurchaseOrderItem.purchase_order_id == PurchaseOrder.id)
         .filter(PurchaseOrderItem.source_pr_item_id == pr_item.id)
         .filter(PurchaseOrder.status.in_(COMMITTED_PO)))
    if exclude_po_id is not None:
        q = q.filter(PurchaseOrder.id != exclude_po_id)
    return q.first() is not None


#: Requisition statuses whose lines may be pulled onto a purchase order.
PULLABLE_PR = ('approved', 'partially_converted')


def pr_ids_blocked_by_pending_amendment(pr_ids=None):
    """Requisitions that may NOT be pulled from because an amendment request is
    awaiting review (owner decision, 2026-08-20).

    ONE query. Pass `pr_ids` to scope it; omit for every pending request.

    Status alone cannot express this: an `approved` requisition with a pending
    request is still `approved`, which is why PULLABLE_PR did not catch it and
    the PO form pulled PR 00001 while the shortcut route refused it
    (BUG-PENDING-AMENDMENT-BLOCK-BYPASSED-BY-THE-PO-FORM).
    """
    from app.purchase_requests.amendment_models import PurchaseRequestAmendmentRequest
    q = (db.session.query(PurchaseRequestAmendmentRequest.purchase_request_id)
         .filter(PurchaseRequestAmendmentRequest.status ==
                 PurchaseRequestAmendmentRequest.STATUS_PENDING))
    if pr_ids is not None:
        ids = [i for i in pr_ids if i is not None]
        if not ids:
            return set()
        q = q.filter(PurchaseRequestAmendmentRequest.purchase_request_id.in_(ids))
    return {r[0] for r in q.distinct().all()}


def assert_no_pending_amendment(allocations):
    """Refuse a submitted payload that pulls from a requisition under amendment.

    The picker already hides these, but hiding an option is not enforcing a rule
    -- a hand-posted `source_pr_item_id` reaches the same code path. Same
    two-layer shape the AP employee-payee fix proved (cas afa15b8a).

    Deliberately NOT folded into assert_payload_within_open_qty: that function is
    shared with Receiving Reports, which allocate against PURCHASE ORDERS and
    have nothing to do with requisition amendments.
    """
    blocked = pr_ids_blocked_by_pending_amendment(
        [pr_item.purchase_request_id for pr_item, _qty, _idx in allocations])
    if not blocked:
        return
    for pr_item, _qty, idx in allocations:
        if pr_item.purchase_request_id in blocked:
            pr = pr_item.purchase_request
            raise ValueError(
                'Line %d: Purchase Requisition "%s" has an amendment request '
                'awaiting review and cannot be ordered until it is approved or '
                'rejected.' % (idx, pr.pr_number if pr else '(unknown)'))


def _pr_item_label(pr_item):
    """How a requisition line is named in a refusal message."""
    return (pr_item.product.name if pr_item.product
            else (pr_item.description or 'this item'))


def assert_payload_within_open_qty(allocations, exclude_po_id=None):
    """Refuse a SUBMITTED PAYLOAD that orders more of a requisition line than
    remains open, counting every line of that payload TOGETHER.

    *allocations* is an ordered iterable of ``(pr_item, qty, idx)`` triples --
    one per submitted line that names a requisition line, in submission order.
    *idx* is that line's 1-based position, used only in the message.

    THE CEILING BELONGS TO THE REQUISITION LINE, NOT TO A PURCHASE-ORDER LINE.
    pr_line_open_qty() sums the PO lines already COMMITTED IN THE DATABASE, so
    nothing in the submission being validated counts towards it. Asking the
    question once per submitted line therefore measured every line against the
    FULL open quantity: the same requisition line pulled twice into one order
    answered "20 <= 20" twice and shipped 40 against 20 open
    (BUG-PR-PO-CEILING-NOT-AGGREGATED-WITHIN-ONE-SUBMISSION). Only the payload's
    per-requisition-line TOTAL is comparable to the ceiling.

    Summed up front and checked ONCE per distinct requisition line, rather than
    by threading a running tally through the caller's per-line loop: the message
    then names the requisition line that is over-ordered and every submitted line
    contributing to it, instead of whichever line happened to tip it over. It
    also means nothing is written before the whole submission is known to fit.

    Refuses at the FIRST over-ordered requisition line in submission order (dicts
    preserve insertion order), so the message is deterministic rather than
    dependent on id ordering.

    An unquantified requisition line has no ceiling, so there is nothing to
    check -- see pr_line_open_qty's None.
    """
    totals = {}
    for pr_item, qty, idx in allocations:
        # Keyed on pr_item.id, not on the instance: the caller resolves each
        # submitted line separately, and two db.session.get() calls for one id
        # need not hand back the same object once the identity map is bypassed.
        slot = totals.setdefault(pr_item.id, [pr_item, Decimal('0'), []])
        slot[1] += Decimal(str(qty or 0))
        slot[2].append(idx)

    for pr_item, total, idxs in totals.values():
        open_qty = pr_line_open_qty(pr_item, exclude_po_id)
        if open_qty is None:
            continue
        if total > open_qty:
            label = _pr_item_label(pr_item)
            if len(idxs) == 1:
                raise ValueError(
                    f'Line {idxs[0]}: only {open_qty} of {label} remain unordered.')
            lines = ', '.join(str(i) for i in idxs)
            raise ValueError(
                f'Lines {lines}: only {open_qty} of {label} remain unordered, '
                f'but these lines order {total} between them.')
    return None


def assert_within_open_qty(pr_item, qty, idx, exclude_po_id=None):
    """Refuse to order more of a requisition line than remains open, ONE line at
    a time.

    Enforced at save rather than by the picker's `max` attribute -- a POST
    bypasses the input entirely. *idx* is the submitted line's 1-based position,
    used only in the message.

    Delegates so there is exactly ONE implementation of the rule: a payload of
    one line is the single-line case, and a second hand-written spelling of a
    ceiling is how the two paths would drift. THIS ENTRY POINT IS NOT SUFFICIENT
    ON ITS OWN for validating a submission -- see assert_payload_within_open_qty,
    which is what a caller holding a whole line array must use.
    """
    return assert_payload_within_open_qty([(pr_item, qty, idx)],
                                          exclude_po_id=exclude_po_id)


def open_lines_for_branch(branch_id, exclude_po_id=None):
    """Every still-open requisition line in *branch_id*, for the PO picker.

    Quantities are returned as STRINGS, not floats: they are Numeric(15, 4) and
    round-tripping them through float would misreport 0.5555 in the very
    column the buyer types into.
    """
    from app.purchase_requests.models import PurchaseRequest, PurchaseRequestItem
    prs = (PurchaseRequest.query
           .filter(PurchaseRequest.branch_id == branch_id,
                   PurchaseRequest.status.in_(PULLABLE_PR))
           .order_by(PurchaseRequest.request_date.asc(), PurchaseRequest.id.asc())
           .all())
    # A pending amendment request blocks ordering, and status cannot say so --
    # the requisition is still `approved`. Resolved ONCE for the whole set, not
    # per requisition.
    blocked = pr_ids_blocked_by_pending_amendment([pr.id for pr in prs])
    prs = [pr for pr in prs if pr.id not in blocked]
    out = []
    for pr in prs:
        for li in pr.line_items:
            if not pr_line_is_open(li, exclude_po_id):
                continue
            open_qty = pr_line_open_qty(li, exclude_po_id)
            out.append({
                'pr_item_id': li.id,
                'pr_id': pr.id,
                'pr_number': pr.pr_number,
                'date_needed': pr.date_needed.isoformat() if pr.date_needed else None,
                'date_needed_asap': bool(pr.date_needed_asap),
                'product_id': li.product_id,
                'product_code': li.product.code if li.product else None,
                'product_name': li.product.name if li.product else None,
                'description': li.description,
                'uom_id': li.unit_of_measure_id,
                'uom_code': (li.unit_of_measure.code if li.unit_of_measure
                             else li.uom_text),
                'requested': _qty_str(li.quantity),
                'ordered': _qty_str(pr_line_ordered_qty(li, exclude_po_id)),
                'open': _qty_str(open_qty),
            })
    return out


def _qty_str(v):
    """Numeric(15, 4) as a trimmed string: '20', '12.5', '' for None."""
    if v is None:
        return ''
    return '{:f}'.format(Decimal(str(v)).normalize())


#: Statuses recompute_pr_status may move between. A draft, submitted, cancelled
#: or rejected requisition is left exactly as it is -- ordering against one is
#: impossible, and resurrecting a cancelled requisition would be a real defect.
RECOMPUTABLE_PR = ('approved', 'partially_converted', 'converted')


def recompute_pr_status(pr):
    """Set and return the requisition's status from its lines' open state.

    Recompute-from-source: this never reads pr.status to decide the answer, so
    it is idempotent and self-repairing. A counter-based design cannot make
    that claim -- one missed decrement is permanent.

    Does NOT commit; the caller owns the transaction.
    """
    if pr.status not in RECOMPUTABLE_PR:
        return pr.status
    lines = list(pr.line_items)
    if not lines:
        pr.status = 'approved'
        return pr.status
    open_count = sum(1 for li in lines if pr_line_is_open(li))
    untouched = sum(1 for li in lines
                    if pr_line_ordered_qty(li) == Decimal('0')
                    and not _has_committed_reference(li))
    if untouched == len(lines):
        pr.status = 'approved'
    elif open_count == 0:
        pr.status = 'converted'
    else:
        pr.status = 'partially_converted'
    return pr.status
