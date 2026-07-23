"""Order Monitoring -- a per-line-item SO/DR delivery-status view, grouped
by customer. Pure query -> dict; no ORM objects escape, so the result is
safe to hand straight to the template. Branch-scoped. DR/Undelivered are
always all-time cumulative for a line -- the date range only controls
which Sales Orders are included, never the figures shown for them.
"""
from decimal import Decimal
from app.sales_orders.models import SalesOrder
from app.delivery_receipts.models import (
    DeliveryReceipt, DeliveryReceiptItem, COMMITTED_STATUSES, so_line_open_qty)


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
        by_customer.setdefault(so.customer_name, []).append(_so_dict(so))

    customers = [
        {'customer_name': name, 'sales_orders': sorted(rows, key=lambda r: r['order_date'])}
        for name, rows in sorted(by_customer.items())
    ]
    return {'customers': customers}


def _so_dict(so):
    return {
        'id': so.id,
        'so_number': so.so_number,
        'order_date': so.order_date,
        'status': so.status,
        'line_items': [_line_item_dict(li) for li in so.line_items],
    }


def _line_item_dict(li):
    base = li.to_dict()
    undelivered = so_line_open_qty(li)
    ordered = Decimal(str(li.quantity or 0))
    delivered = ordered - undelivered
    base['dr_qty'] = float(delivered)
    base['undelivered_qty'] = float(undelivered)
    base['deliveries'] = _deliveries(li)
    return base


def _deliveries(li):
    rows = (DeliveryReceiptItem.query
           .join(DeliveryReceipt, DeliveryReceiptItem.delivery_receipt_id == DeliveryReceipt.id)
           .filter(DeliveryReceiptItem.sales_order_item_id == li.id,
                   DeliveryReceipt.status.in_(COMMITTED_STATUSES))
           .order_by(DeliveryReceipt.delivery_date).all())
    return [
        {'dr_id': r.delivery_receipt_id, 'dr_number': r.delivery_receipt.dr_number,
         'delivery_date': r.delivery_receipt.delivery_date,
         'quantity': float(r.delivered_quantity)}
        for r in rows
    ]
