"""A Sales Order's header closes itself (SO-CLOSED A, owner 22 Nov 2026).

A confirmed order turns 'closed' once every line is done -- fully delivered by committed
Delivery Receipts, or closed short -- and goes back to 'confirmed' when quantity opens again
(a committed DR cancelled). Before this, 'closed' was declared in VALID_SO_STATUSES, offered in
the list filter and honoured by so_line_open_qty and the cancel guard, but nothing ever set it
(BUG-SO-CLOSED-STATUS-DECLARED-BUT-UNREACHABLE). A Purchase Order already closes itself, on
billing (app/purchase_billing.py).

The status is re-judged at each event that can change it: a DR approved or cancelled, a line
closed short, an amendment saved. Each caller syncs BEFORE its commit, so the header moves in
the same transaction as its cause, then calls report_status_changes() AFTER the commit, because
log_audit commits on its own.
"""
from decimal import Decimal

from flask import flash

from app import db


def _line_done(item):
    from app.delivery_receipts.models import so_line_committed_qty
    if item.line_status == 'closed':
        return True
    return so_line_committed_qty(item) >= Decimal(str(item.quantity or 0))


def sync_status(so):
    """Move a confirmed/closed order to the status its lines call for.

    Returns (so, old, new) when the status changed, else None. Draft and cancelled orders are
    never touched. The caller commits."""
    if so is None or so.status not in ('confirmed', 'closed'):
        return None
    lines = list(so.line_items)
    new = 'closed' if lines and all(_line_done(li) for li in lines) else 'confirmed'
    if new == so.status:
        return None
    old, so.status = so.status, new
    return so, old, new


def sync_orders_of_dr(dr):
    """sync_status for every order a Delivery Receipt touches: its header's order and the
    orders of its lines (a DR-NOSO receipt has neither, and changes nothing)."""
    from app.sales_orders.models import SalesOrder
    ids = {dr.sales_order_id} if dr.sales_order_id else set()
    ids.update(li.sales_order_item.sales_order_id for li in dr.line_items
               if li.sales_order_item is not None)
    changes = (sync_status(db.session.get(SalesOrder, i)) for i in sorted(ids))
    return [c for c in changes if c]


def report_status_changes(changes, cause):
    """After the caller's commit: one audit row and one message per order that moved."""
    from app.audit.utils import log_update
    for so, old, new in changes:
        verb = 'Closed' if new == 'closed' else 'Reopened'
        log_update(module='sales_orders', record_id=so.id,
                   record_identifier=f'{so.so_number} - {so.customer_name}',
                   old_values={'status': old}, new_values={'status': new},
                   notes=f'{verb} automatically: {cause}')
        if new == 'closed':
            flash(f'Sales Order "{so.so_number}" is now Closed: every line is delivered '
                  f'or closed short.', 'info')
        else:
            flash(f'Sales Order "{so.so_number}" is back to Confirmed: quantity is open '
                  f'again ({cause}).', 'info')
