from decimal import Decimal
from datetime import timedelta
from app.utils import ph_now

OPEN_STATUSES = ('posted', 'partially_paid')


def compute_invoices_summary(branch_id):
    """Summary metrics for the sales invoices list page cards.

    Keys: outstanding_total/_count, overdue_total/_count,
    due_soon_total/_count (due within 7 days), draft_count.
    """
    from app import db
    from app.sales_invoices.models import SalesInvoice
    today = ph_now().date()

    def _agg(*extra_filters):
        total, count = (
            db.session.query(
                db.func.coalesce(db.func.sum(SalesInvoice.balance), 0),
                db.func.count(SalesInvoice.id),
            )
            .filter(
                SalesInvoice.branch_id == branch_id,
                SalesInvoice.status.in_(OPEN_STATUSES),
                *extra_filters,
            )
            .one()
        )
        return Decimal(str(total)).quantize(Decimal('0.01')), count

    outstanding_total, outstanding_count = _agg()
    overdue_total, overdue_count = _agg(
        SalesInvoice.due_date.isnot(None),
        SalesInvoice.due_date < today,
    )
    due_soon_total, due_soon_count = _agg(
        SalesInvoice.due_date.isnot(None),
        SalesInvoice.due_date >= today,
        SalesInvoice.due_date <= today + timedelta(days=7),
    )
    draft_count = (
        db.session.query(db.func.count(SalesInvoice.id))
        .filter(
            SalesInvoice.branch_id == branch_id,
            SalesInvoice.status == 'draft',
        )
        .scalar()
    )
    return {
        'outstanding_total': outstanding_total,
        'outstanding_count': outstanding_count,
        'overdue_total': overdue_total,
        'overdue_count': overdue_count,
        'due_soon_total': due_soon_total,
        'due_soon_count': due_soon_count,
        'draft_count': draft_count,
    }
