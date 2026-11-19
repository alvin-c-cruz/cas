"""Order Monitoring's DR column shows what was actually delivered (SOM).

Owner, 14 Nov 2026: "SOM yes" (work order 2026-08-06-so-monitor-closed-line-dr-overstated). DR was computed as
ordered minus so_line_open_qty, and so_line_open_qty returns 0 for a short-closed line or a cancelled/closed order, so
the whole ordered quantity read as delivered -- at exactly the moment the user said the rest would not ship. Now DR is
the sum of the line's committed delivery receipts (the same rows the drill-down lists); Undelivered keeps reading
so_line_open_qty, which is 0 for those lines on purpose (nothing more will ship).
"""
from datetime import date
from decimal import Decimal

import pytest

from app.delivery_receipts.models import DeliveryReceipt, DeliveryReceiptItem
from app.sales_orders.models import SalesOrder, SalesOrderItem
from app.sales_orders.monitoring import get_order_monitoring

pytestmark = [pytest.mark.integration, pytest.mark.sales_orders]

N = iter(range(1, 1000))


def _so(db_session, branch_id, status='confirmed', lines=((Decimal('10'), 'open'),)):
    n = next(N)
    so = SalesOrder(so_number=f'SO-RQ-{n:04d}', order_date=date(2026, 7, 5), customer_id=1,
                    customer_name='Acme', branch_id=branch_id, status=status)
    for i, (qty, line_status) in enumerate(lines, start=1):
        so.line_items.append(SalesOrderItem(line_number=i, quantity=qty, unit_price=Decimal('10.00'),
                                            amount=qty * 10, line_status=line_status))
    db_session.add(so)
    db_session.commit()
    return so


def _dr(db_session, so, li, qty, status='delivered'):
    n = next(N)
    dr = DeliveryReceipt(dr_number=f'DR-RQ-{n:04d}', delivery_date=date(2026, 7, 10), sales_order_id=so.id,
                         customer_id=1, customer_name='Acme', status=status, branch_id=so.branch_id)
    db_session.add(dr)
    db_session.commit()
    dr.line_items.append(DeliveryReceiptItem(line_number=1, sales_order_item_id=li.id,
                                             delivered_quantity=Decimal(str(qty))))
    db_session.commit()


def _lines(branch_id):
    out = {}
    for c in get_order_monitoring(branch_id, date(2026, 7, 1), date(2026, 7, 31))['customers']:
        for so in c['sales_orders']:
            for li in so['line_items']:
                out[(so['so_number'], li['line_number'])] = (li['dr_qty'], li['undelivered_qty'])
    return out


def test_a_short_closed_line_shows_only_what_was_delivered(db_session, main_branch):
    so = _so(db_session, main_branch.id, lines=((Decimal('10'), 'closed'), (Decimal('10'), 'open')))
    _dr(db_session, so, so.line_items[0], 4)
    _dr(db_session, so, so.line_items[1], 3)
    got = _lines(main_branch.id)
    assert got[(so.so_number, 1)] == (4.0, 0.0), 'closed: 4 delivered, nothing more to come'
    assert got[(so.so_number, 2)] == (3.0, 7.0), 'control: the open sibling is unchanged'


def test_a_closed_line_with_no_deliveries_shows_zero(db_session, main_branch):
    so = _so(db_session, main_branch.id, lines=((Decimal('10'), 'closed'),))
    assert _lines(main_branch.id)[(so.so_number, 1)] == (0.0, 0.0)


@pytest.mark.parametrize('status', ['cancelled', 'closed'])
def test_a_cancelled_or_closed_order_shows_only_what_was_delivered(db_session, main_branch, status):
    so = _so(db_session, main_branch.id, status=status)
    _dr(db_session, so, so.line_items[0], 2)
    assert _lines(main_branch.id)[(so.so_number, 1)] == (2.0, 0.0)


def test_draft_and_cancelled_drs_still_do_not_count(db_session, main_branch):
    so = _so(db_session, main_branch.id)
    _dr(db_session, so, so.line_items[0], 5, status='draft')
    _dr(db_session, so, so.line_items[0], 1, status='delivered')
    assert _lines(main_branch.id)[(so.so_number, 1)] == (1.0, 9.0)
