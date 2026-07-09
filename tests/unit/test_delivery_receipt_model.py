import pytest
from datetime import date
from decimal import Decimal
from app import db
from app.customers.models import Customer
from app.products.models import Product
from app.sales_orders.models import SalesOrder, SalesOrderItem
from app.delivery_receipts.models import (
    DeliveryReceipt, DeliveryReceiptItem, so_line_open_qty, post_delivery_je)

pytestmark = [pytest.mark.integration, pytest.mark.delivery_receipts]


def _so_with_line(db_session, branch_id, ordered='10'):
    c = Customer(code='C-DR', name='DR Corp', is_active=True)
    p = Product(code='W', name='Widget', is_active=True)
    db.session.add_all([c, p]); db.session.commit()
    so = SalesOrder(so_number='SO-DR-1', order_date=date(2026, 7, 9), customer_id=c.id,
                    customer_name='DR Corp', branch_id=branch_id, status='confirmed')
    li = SalesOrderItem(line_number=1, product_id=p.id, quantity=Decimal(ordered),
                        unit_price=Decimal('100'), amount=Decimal('1000'))
    so.line_items.append(li)
    db.session.add(so); db.session.commit()
    return so, li


def _dr(db_session, so, so_item, branch_id, qty, status):
    dr = DeliveryReceipt(dr_number=f'DR-T-{status}-{qty}', branch_id=branch_id,
                         sales_order_id=so.id, customer_id=so.customer_id,
                         customer_name=so.customer_name, delivery_date=date(2026, 7, 9),
                         status=status)
    dr.line_items.append(DeliveryReceiptItem(line_number=1, sales_order_item_id=so_item.id,
                                             product_id=so_item.product_id,
                                             delivered_quantity=Decimal(qty)))
    db.session.add(dr); db.session.commit()
    return dr


def test_open_qty_ignores_draft_counts_committed_releases_cancelled(db_session, main_branch):
    so, li = _so_with_line(db_session, main_branch.id, ordered='10')
    assert so_line_open_qty(li) == Decimal('10')          # nothing delivered yet
    _dr(db_session, so, li, main_branch.id, '3', 'draft')   # draft -> does NOT count
    assert so_line_open_qty(li) == Decimal('10')
    _dr(db_session, so, li, main_branch.id, '4', 'approved')  # committed
    assert so_line_open_qty(li) == Decimal('6')
    _dr(db_session, so, li, main_branch.id, '2', 'cancelled')  # released
    assert so_line_open_qty(li) == Decimal('6')


def test_to_dict_and_post_seam(db_session, main_branch):
    so, li = _so_with_line(db_session, main_branch.id)
    dr = _dr(db_session, so, li, main_branch.id, '5', 'draft')
    d = dr.to_dict()
    assert d['status'] == 'draft' and d['sales_order_number'] == 'SO-DR-1'
    assert dr.line_items[0].to_dict()['delivered_quantity'] == 5.0
    assert dr.line_items[0].to_dict()['ordered_quantity'] == 10.0
    assert post_delivery_je(dr) is None      # inert R-03 seam


def test_qty_fmt_renders_delivered_quantity(db_session, main_branch):
    """The `qty_fmt` filter duck-types on `item.quantity` / `unit_of_measure` / `uom_text`.
    A DR line stores `delivered_quantity`, so without the aliases the filter renders blank."""
    from app.utils import format_line_qty
    so, li = _so_with_line(db_session, main_branch.id)
    dr = _dr(db_session, so, li, main_branch.id, '4', 'draft')
    item = dr.line_items[0]
    assert item.quantity == Decimal('4')
    assert format_line_qty(item) == '4.0000'


def test_exclude_dr_id_leaves_that_dr_out_of_committed_sum(db_session, main_branch):
    so, li = _so_with_line(db_session, main_branch.id, ordered='10')
    dr = _dr(db_session, so, li, main_branch.id, '4', 'approved')
    assert so_line_open_qty(li) == Decimal('6')
    assert so_line_open_qty(li, exclude_dr_id=dr.id) == Decimal('10')
