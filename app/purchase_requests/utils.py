"""Summary metrics for the Purchase Requests list page cards."""
from app import db
from app.purchase_requests.models import PurchaseRequest


def compute_pr_summary(branch_id):
    """Return the counts behind the Purchase Requests list page cards.

    Keys: draft_count, pending_approval_count, approved_count, converted_count.
    Branch-scoped.

    `pending_approval_count` reads the APPROVAL FACT, not `status == 'submitted'`.
    Since 2026-09-06 a requisition pulled onto an order before its signature
    arrives is moved on by recompute_pr_status, so it can read
    `partially_converted` while still unsigned -- counting only `submitted` would
    have dropped exactly those from the card that exists to chase them, and the
    card would have said 0 while somebody was still waiting to sign.

    The other three stay status counts: they ask where the goods have got, which
    IS what the status records.
    """
    def _count(status):
        return (db.session.query(db.func.count(PurchaseRequest.id))
                .filter(PurchaseRequest.branch_id == branch_id,
                        PurchaseRequest.status == status)
                .scalar())

    pending = (db.session.query(db.func.count(PurchaseRequest.id))
               .filter(PurchaseRequest.branch_id == branch_id,
                       PurchaseRequest.approved_by_id.is_(None),
                       PurchaseRequest.status.notin_(
                           PurchaseRequest.NEVER_AWAITING_APPROVAL))
               .scalar())

    return {
        'draft_count': _count('draft'),
        'pending_approval_count': pending,
        'approved_count': _count('approved'),
        'converted_count': _count('converted'),
    }
