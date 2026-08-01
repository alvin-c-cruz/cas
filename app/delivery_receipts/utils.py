"""Summary metrics for the delivery receipts list page's stat cards."""
from app import db


def compute_delivery_receipts_summary(branch_id):
    """Keys: draft_count, awaiting_count (approved, not yet delivered),
    unbilled_count (delivered, not yet billed), billed_count."""
    from app.delivery_receipts.models import DeliveryReceipt

    def _count(status):
        return (
            db.session.query(db.func.count(DeliveryReceipt.id))
            .filter(DeliveryReceipt.branch_id == branch_id, DeliveryReceipt.status == status)
            .scalar()
        )

    return {
        'draft_count': _count('draft'),
        'awaiting_count': _count('approved'),
        'unbilled_count': _count('delivered'),
        'billed_count': _count('billed'),
    }
