"""Order Monitoring -- a document-level SO/DR/SI status view, grouped by
customer. Pure query -> dict; no ORM objects escape (except via the
already-shipped SalesOrderItem.to_dict()), so the result is safe to hand
straight to the template. Branch-scoped.
"""
from app.sales_orders.models import SalesOrder


def get_order_monitoring(branch_id, date_from, date_to):
    in_range = SalesOrder.query.filter(
        SalesOrder.branch_id == branch_id,
        SalesOrder.order_date >= date_from,
        SalesOrder.order_date <= date_to,
    ).all()
    carried_forward = SalesOrder.query.filter(
        SalesOrder.branch_id == branch_id,
        SalesOrder.order_date < date_from,
        SalesOrder.status == 'confirmed',
    ).all()

    by_customer = {}
    for so in in_range + carried_forward:
        by_customer.setdefault(so.customer_name, []).append(_so_dict(so, date_from, date_to))

    customers = [
        {'customer_name': name, 'sales_orders': sorted(rows, key=lambda r: r['order_date'])}
        for name, rows in sorted(by_customer.items())
    ]
    return {'customers': customers}


def _so_dict(so, date_from, date_to):
    return {
        'id': so.id,
        'so_number': so.so_number,
        'order_date': so.order_date,
        'status': so.status,
        'line_items': [li.to_dict() for li in so.line_items],
        'delivery_receipts': [],
    }
