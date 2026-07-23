"""Summary metrics for the Receiving Reports list page cards."""
from app import db
from app.receiving_reports.models import ReceivingReport


def compute_rr_summary(branch_id):
    """Return status-bucket counts for the Receiving Reports list page cards.

    Keys: draft_count, pending_billing_count (status='approved'), billed_count.
    Branch-scoped.
    """
    def _count(status):
        return (db.session.query(db.func.count(ReceivingReport.id))
                .filter(ReceivingReport.branch_id == branch_id,
                        ReceivingReport.status == status)
                .scalar())

    return {
        'draft_count': _count('draft'),
        'pending_billing_count': _count('approved'),
        'billed_count': _count('billed'),
    }
