"""Summary metrics for the sales orders list page's stat cards."""
from datetime import timedelta
from decimal import Decimal

from app import db
from app.utils import ph_now


def compute_sales_orders_summary(branch_id):
    """Keys: open_total/_count (confirmed orders), overdue_count/due_soon_count
    (confirmed orders vs. expected_delivery_date), draft_count."""
    from app.sales_orders.models import SalesOrder
    today = ph_now().date()

    open_total, open_count = (
        db.session.query(
            db.func.coalesce(db.func.sum(SalesOrder.total_amount), 0),
            db.func.count(SalesOrder.id),
        )
        .filter(SalesOrder.branch_id == branch_id, SalesOrder.status == 'confirmed')
        .one()
    )

    def _count(*extra_filters):
        return (
            db.session.query(db.func.count(SalesOrder.id))
            .filter(SalesOrder.branch_id == branch_id, SalesOrder.status == 'confirmed',
                    *extra_filters)
            .scalar()
        )

    overdue_count = _count(
        SalesOrder.expected_delivery_date.isnot(None),
        SalesOrder.expected_delivery_date < today,
    )
    due_soon_count = _count(
        SalesOrder.expected_delivery_date.isnot(None),
        SalesOrder.expected_delivery_date >= today,
        SalesOrder.expected_delivery_date <= today + timedelta(days=7),
    )
    draft_count = (
        db.session.query(db.func.count(SalesOrder.id))
        .filter(SalesOrder.branch_id == branch_id, SalesOrder.status == 'draft')
        .scalar()
    )

    return {
        'open_total': Decimal(str(open_total)).quantize(Decimal('0.01')),
        'open_count': open_count,
        'overdue_count': overdue_count,
        'due_soon_count': due_soon_count,
        'draft_count': draft_count,
    }
