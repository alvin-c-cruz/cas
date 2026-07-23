"""Summary metrics for the Purchase Requests list page cards."""
from app import db
from app.purchase_requests.models import PurchaseRequest


def compute_pr_summary(branch_id):
    """Return status-bucket counts for the Purchase Requests list page cards.

    Keys: draft_count, pending_approval_count (status='submitted'), approved_count
    (approved, not yet converted), converted_count. Branch-scoped.
    """
    def _count(status):
        return (db.session.query(db.func.count(PurchaseRequest.id))
                .filter(PurchaseRequest.branch_id == branch_id,
                        PurchaseRequest.status == status)
                .scalar())

    return {
        'draft_count': _count('draft'),
        'pending_approval_count': _count('submitted'),
        'approved_count': _count('approved'),
        'converted_count': _count('converted'),
    }
