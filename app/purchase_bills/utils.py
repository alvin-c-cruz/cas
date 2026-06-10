from decimal import Decimal
from datetime import timedelta
from app.utils import ph_now

# Statuses that carry an outstanding payable balance
OPEN_STATUSES = ('posted', 'partially_paid')


def compute_bills_summary(branch_id):
    """Return summary metrics for the purchase bills list page cards.

    Keys: outstanding_total/_count, overdue_total/_count,
    due_soon_total/_count (due within 7 days), draft_count.
    Amounts are Decimal sums of bill.balance over open bills in the branch.
    """
    from app import db
    from app.purchase_bills.models import PurchaseBill
    today = ph_now().date()

    def _agg(*extra_filters):
        total, count = (
            db.session.query(
                db.func.coalesce(db.func.sum(PurchaseBill.balance), 0),
                db.func.count(PurchaseBill.id),
            )
            .filter(
                PurchaseBill.branch_id == branch_id,
                PurchaseBill.status.in_(OPEN_STATUSES),
                *extra_filters,
            )
            .one()
        )
        return Decimal(str(total)).quantize(Decimal('0.01')), count

    outstanding_total, outstanding_count = _agg()
    overdue_total, overdue_count = _agg(
        PurchaseBill.due_date.isnot(None),
        PurchaseBill.due_date < today,
    )
    due_soon_total, due_soon_count = _agg(
        PurchaseBill.due_date.isnot(None),
        PurchaseBill.due_date >= today,
        PurchaseBill.due_date <= today + timedelta(days=7),
    )
    draft_count = PurchaseBill.query.filter_by(
        branch_id=branch_id, status='draft').count()

    return {
        'outstanding_total': outstanding_total,
        'outstanding_count': outstanding_count,
        'overdue_total': overdue_total,
        'overdue_count': overdue_count,
        'due_soon_total': due_soon_total,
        'due_soon_count': due_soon_count,
        'draft_count': draft_count,
    }
