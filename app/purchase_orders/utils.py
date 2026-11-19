"""Summary metrics for the Purchase Orders list page cards."""
from decimal import Decimal
from app import db
from app.purchase_orders.models import PurchaseOrder

OPEN_PO_STATUSES = ('approved', 'partially_received')
#: The list page's "to approve" card: drafts AND submitted orders, everything not yet
#: approved (POC A, owner 14 Nov 2026). A submitted order used to be counted by no card.
TO_APPROVE_PO_STATUSES = ('draft', 'submitted')


def compute_po_summary(branch_id):
    """Return status-bucket counts + open total value for the Purchase Orders list
    page cards. Keys: draft_count (draft + submitted), open_count (approved + partially_received),
    closed_count, open_value_total (Decimal). Branch-scoped.
    """
    def _count(status):
        return (db.session.query(db.func.count(PurchaseOrder.id))
                .filter(PurchaseOrder.branch_id == branch_id, PurchaseOrder.status == status)
                .scalar())

    open_total, open_count = (
        db.session.query(
            db.func.coalesce(db.func.sum(PurchaseOrder.total_amount), 0),
            db.func.count(PurchaseOrder.id),
        )
        .filter(PurchaseOrder.branch_id == branch_id,
                PurchaseOrder.status.in_(OPEN_PO_STATUSES))
        .one()
    )

    draft_count = (db.session.query(db.func.count(PurchaseOrder.id))
                   .filter(PurchaseOrder.branch_id == branch_id,
                           PurchaseOrder.status.in_(TO_APPROVE_PO_STATUSES))
                   .scalar())

    return {
        'draft_count': draft_count,
        'open_count': open_count,
        'closed_count': _count('closed'),
        'open_value_total': Decimal(str(open_total)).quantize(Decimal('0.01')),
    }
