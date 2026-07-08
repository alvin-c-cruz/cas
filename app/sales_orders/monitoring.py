"""Read-only, count-based metrics for the Order Monitoring dashboard.

Pure query -> dict; no ORM objects escape, so the result is safe to hand straight
to the template. `today` is a parameter for deterministic tests. Branch-scoped.
"""
from datetime import timedelta
from sqlalchemy import func
from app.sales_orders.models import SalesOrder


def get_order_monitoring(branch_id, today):
    base = SalesOrder.query.filter_by(branch_id=branch_id)
    confirmed = base.filter_by(status='confirmed')

    open_ct = confirmed.count()
    drafts = base.filter_by(status='draft').count()
    cancelled = base.filter_by(status='cancelled').count()

    overdue = confirmed.filter(
        SalesOrder.expected_delivery_date.isnot(None),
        SalesOrder.expected_delivery_date < today).count()
    soon_end = today + timedelta(days=7)
    due_soon = confirmed.filter(
        SalesOrder.expected_delivery_date.isnot(None),
        SalesOrder.expected_delivery_date >= today,
        SalesOrder.expected_delivery_date <= soon_end).count()

    # aging of open (confirmed) orders by days since order_date
    aging = [0, 0, 0, 0]  # 0-7, 8-30, 31-60, 60+
    for (od,) in confirmed.with_entities(SalesOrder.order_date).all():
        days = (today - od).days
        if days <= 7:
            aging[0] += 1
        elif days <= 30:
            aging[1] += 1
        elif days <= 60:
            aging[2] += 1
        else:
            aging[3] += 1

    rows = (confirmed.with_entities(SalesOrder.customer_name, func.count(SalesOrder.id))
            .group_by(SalesOrder.customer_name)
            .order_by(func.count(SalesOrder.id).desc(), SalesOrder.customer_name)
            .limit(5).all())
    top_customers = [{'customer_name': name, 'count': cnt} for (name, cnt) in rows]

    return {
        'cards': {'open': open_ct, 'drafts': drafts, 'overdue': overdue, 'due_soon': due_soon},
        'by_status': {'labels': ['Draft', 'Confirmed', 'Cancelled'],
                      'data': [drafts, open_ct, cancelled]},
        'aging': {'labels': ['0-7', '8-30', '31-60', '60+'], 'data': aging},
        'top_customers': top_customers,
    }
