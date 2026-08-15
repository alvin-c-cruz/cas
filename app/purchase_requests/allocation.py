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


def assert_within_open_qty(pr_item, qty, idx, exclude_po_id=None):
    """Refuse to order more of a requisition line than remains open.

    Enforced HERE, at save, rather than by the picker's `max` attribute -- a
    POST bypasses the input entirely. *idx* is the submitted line's 1-based
    position, used only in the message.

    An unquantified requisition line has no ceiling, so there is nothing to
    check.
    """
    open_qty = pr_line_open_qty(pr_item, exclude_po_id)
    if open_qty is None:
        return None
    if Decimal(str(qty or 0)) > open_qty:
        label = (pr_item.product.name if pr_item.product
                 else (pr_item.description or 'this item'))
        raise ValueError(
            f'Line {idx}: only {open_qty} of {label} remain unordered.')
    return None


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
