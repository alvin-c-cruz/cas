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
