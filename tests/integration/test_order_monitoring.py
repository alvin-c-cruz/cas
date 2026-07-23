import pytest
from datetime import date
from app import db
from app.sales_orders.models import SalesOrder
from app.sales_orders.monitoring import get_order_monitoring

pytestmark = [pytest.mark.integration, pytest.mark.sales_orders]


def _so(db_session, branch_id, n, status, order_date, customer='Acme'):
    so = SalesOrder(so_number=f'SO-MON-{n:04d}', order_date=order_date, customer_id=1,
                    customer_name=customer, branch_id=branch_id, status=status)
    db_session.add(so); db_session.commit()
    return so


def test_includes_in_range_so(db_session, main_branch):
    b = main_branch.id
    _so(db_session, b, 1, 'confirmed', date(2026, 7, 5), 'Acme')
    result = get_order_monitoring(b, date(2026, 7, 1), date(2026, 7, 31))
    assert result['customers'] == [{'customer_name': 'Acme', 'sales_orders': [
        {'id': result['customers'][0]['sales_orders'][0]['id'], 'so_number': 'SO-MON-0001',
         'order_date': date(2026, 7, 5), 'status': 'confirmed', 'line_items': []},
    ]}]


def test_excludes_out_of_range_non_open_so(db_session, main_branch):
    b = main_branch.id
    _so(db_session, b, 1, 'confirmed', date(2026, 6, 5), 'Acme')  # out of range, but confirmed -> carries forward (covered by next test)
    _so(db_session, b, 2, 'draft', date(2026, 6, 5), 'Beta')      # out of range, draft -> excluded
    _so(db_session, b, 3, 'closed', date(2026, 6, 5), 'Gamma')    # out of range, closed -> excluded
    _so(db_session, b, 4, 'cancelled', date(2026, 6, 5), 'Delta') # out of range, cancelled -> excluded
    result = get_order_monitoring(b, date(2026, 7, 1), date(2026, 7, 31))
    names = {c['customer_name'] for c in result['customers']}
    assert names == {'Acme'}   # only the carried-forward confirmed one


def test_carries_forward_confirmed_so_from_before_range(db_session, main_branch):
    b = main_branch.id
    _so(db_session, b, 1, 'confirmed', date(2026, 5, 1), 'Acme')
    result = get_order_monitoring(b, date(2026, 7, 1), date(2026, 7, 31))
    assert len(result['customers']) == 1
    assert result['customers'][0]['sales_orders'][0]['so_number'] == 'SO-MON-0001'
    assert result['customers'][0]['sales_orders'][0]['order_date'] == date(2026, 5, 1)


def test_does_not_carry_forward_draft_so(db_session, main_branch):
    b = main_branch.id
    _so(db_session, b, 1, 'draft', date(2026, 5, 1), 'Acme')
    result = get_order_monitoring(b, date(2026, 7, 1), date(2026, 7, 31))
    assert result['customers'] == []


def test_groups_by_customer_and_sorts_by_order_date_within_group(db_session, main_branch):
    b = main_branch.id
    _so(db_session, b, 1, 'confirmed', date(2026, 7, 20), 'Acme')
    _so(db_session, b, 2, 'confirmed', date(2026, 7, 5), 'Acme')
    _so(db_session, b, 3, 'confirmed', date(2026, 7, 10), 'Beta')
    result = get_order_monitoring(b, date(2026, 7, 1), date(2026, 7, 31))
    names = [c['customer_name'] for c in result['customers']]
    assert names == ['Acme', 'Beta']
    acme_dates = [so['order_date'] for so in result['customers'][0]['sales_orders']]
    assert acme_dates == [date(2026, 7, 5), date(2026, 7, 20)]


def test_branch_isolation(db_session, main_branch, branch_manila):
    _so(db_session, main_branch.id, 1, 'confirmed', date(2026, 7, 5), 'Acme')
    _so(db_session, branch_manila.id, 2, 'confirmed', date(2026, 7, 5), 'Beta')
    result = get_order_monitoring(main_branch.id, date(2026, 7, 1), date(2026, 7, 31))
    names = {c['customer_name'] for c in result['customers']}
    assert names == {'Acme'}


def test_line_items_included_via_existing_to_dict(db_session, main_branch):
    from decimal import Decimal
    from app.sales_orders.models import SalesOrderItem
    b = main_branch.id
    so = _so(db_session, b, 1, 'confirmed', date(2026, 7, 5), 'Acme')
    so.line_items.append(SalesOrderItem(line_number=1, quantity=Decimal('2'),
                                        unit_price=Decimal('100.00'), amount=Decimal('200.00')))
    db_session.commit()
    result = get_order_monitoring(b, date(2026, 7, 1), date(2026, 7, 31))
    items = result['customers'][0]['sales_orders'][0]['line_items']
    assert len(items) == 1
    assert items[0]['quantity'] == 2.0
    assert items[0]['unit_price'] == 100.0


def test_line_item_dr_and_undelivered_reconcile_with_so_qty(db_session, main_branch):
    from decimal import Decimal
    from app.sales_orders.models import SalesOrderItem
    from app.delivery_receipts.models import DeliveryReceipt, DeliveryReceiptItem
    b = main_branch.id
    so = _so(db_session, b, 1, 'confirmed', date(2026, 7, 5), 'Acme')
    li = SalesOrderItem(line_number=1, quantity=Decimal('500'), unit_price=Decimal('18.50'),
                        amount=Decimal('9250.00'))
    so.line_items.append(li); db_session.commit()
    dr = DeliveryReceipt(dr_number='DR-MON-0001', delivery_date=date(2026, 7, 10),
                         sales_order_id=so.id, customer_id=1, customer_name='Acme',
                         status='delivered', branch_id=b)
    db_session.add(dr); db_session.commit()
    dr.line_items.append(DeliveryReceiptItem(line_number=1, sales_order_item_id=li.id,
                                             delivered_quantity=Decimal('350')))
    db_session.commit()

    result = get_order_monitoring(b, date(2026, 7, 1), date(2026, 7, 31))
    out_li = result['customers'][0]['sales_orders'][0]['line_items'][0]
    assert out_li['quantity'] == 500.0
    assert out_li['dr_qty'] == 350.0
    assert out_li['undelivered_qty'] == 150.0
    assert out_li['quantity'] == out_li['dr_qty'] + out_li['undelivered_qty']


def test_line_item_with_no_deliveries_shows_zero_dr(db_session, main_branch):
    from decimal import Decimal
    from app.sales_orders.models import SalesOrderItem
    b = main_branch.id
    so = _so(db_session, b, 1, 'confirmed', date(2026, 7, 5), 'Acme')
    li = SalesOrderItem(line_number=1, quantity=Decimal('200'), unit_price=Decimal('10.00'),
                        amount=Decimal('2000.00'))
    so.line_items.append(li); db_session.commit()
    result = get_order_monitoring(b, date(2026, 7, 1), date(2026, 7, 31))
    out_li = result['customers'][0]['sales_orders'][0]['line_items'][0]
    assert out_li['dr_qty'] == 0.0
    assert out_li['undelivered_qty'] == 200.0
    assert out_li['deliveries'] == []


def test_draft_dr_does_not_count_toward_dr_qty(db_session, main_branch):
    from decimal import Decimal
    from app.sales_orders.models import SalesOrderItem
    from app.delivery_receipts.models import DeliveryReceipt, DeliveryReceiptItem
    b = main_branch.id
    so = _so(db_session, b, 1, 'confirmed', date(2026, 7, 5), 'Acme')
    li = SalesOrderItem(line_number=1, quantity=Decimal('100'), unit_price=Decimal('5.00'),
                        amount=Decimal('500.00'))
    so.line_items.append(li); db_session.commit()
    dr = DeliveryReceipt(dr_number='DR-MON-0002', delivery_date=date(2026, 7, 10),
                         sales_order_id=so.id, customer_id=1, customer_name='Acme',
                         status='draft', branch_id=b)
    db_session.add(dr); db_session.commit()
    dr.line_items.append(DeliveryReceiptItem(line_number=1, sales_order_item_id=li.id,
                                             delivered_quantity=Decimal('40')))
    db_session.commit()
    result = get_order_monitoring(b, date(2026, 7, 1), date(2026, 7, 31))
    out_li = result['customers'][0]['sales_orders'][0]['line_items'][0]
    assert out_li['dr_qty'] == 0.0
    assert out_li['undelivered_qty'] == 100.0
    assert out_li['deliveries'] == []


def test_dr_qty_is_all_time_not_scoped_to_selected_range(db_session, main_branch):
    """A carried-forward SO's line item shows its WHOLE delivery history, even
    though its delivery happened before the visible date range."""
    from decimal import Decimal
    from app.sales_orders.models import SalesOrderItem
    from app.delivery_receipts.models import DeliveryReceipt, DeliveryReceiptItem
    b = main_branch.id
    so = _so(db_session, b, 1, 'confirmed', date(2026, 5, 1), 'Acme')  # carried forward into July view
    li = SalesOrderItem(line_number=1, quantity=Decimal('1000'), unit_price=Decimal('18.50'),
                        amount=Decimal('18500.00'))
    so.line_items.append(li); db_session.commit()
    dr = DeliveryReceipt(dr_number='DR-MON-0003', delivery_date=date(2026, 5, 5),  # before the July range
                         sales_order_id=so.id, customer_id=1, customer_name='Acme',
                         status='delivered', branch_id=b)
    db_session.add(dr); db_session.commit()
    dr.line_items.append(DeliveryReceiptItem(line_number=1, sales_order_item_id=li.id,
                                             delivered_quantity=Decimal('400')))
    db_session.commit()
    result = get_order_monitoring(b, date(2026, 7, 1), date(2026, 7, 31))
    out_li = result['customers'][0]['sales_orders'][0]['line_items'][0]
    assert out_li['dr_qty'] == 400.0    # counted even though the DR predates the visible range
    assert out_li['undelivered_qty'] == 600.0


def test_deliveries_breakdown_lists_each_contributing_dr(db_session, main_branch):
    from decimal import Decimal
    from app.sales_orders.models import SalesOrderItem
    from app.delivery_receipts.models import DeliveryReceipt, DeliveryReceiptItem
    b = main_branch.id
    so = _so(db_session, b, 1, 'confirmed', date(2026, 7, 5), 'Acme')
    li = SalesOrderItem(line_number=1, quantity=Decimal('500'), unit_price=Decimal('18.50'),
                        amount=Decimal('9250.00'))
    so.line_items.append(li); db_session.commit()
    dr1 = DeliveryReceipt(dr_number='DR-MON-0004', delivery_date=date(2026, 7, 8),
                          sales_order_id=so.id, customer_id=1, customer_name='Acme',
                          status='delivered', branch_id=b)
    dr2 = DeliveryReceipt(dr_number='DR-MON-0005', delivery_date=date(2026, 7, 19),
                          sales_order_id=so.id, customer_id=1, customer_name='Acme',
                          status='delivered', branch_id=b)
    db_session.add_all([dr1, dr2]); db_session.commit()
    dr1.line_items.append(DeliveryReceiptItem(line_number=1, sales_order_item_id=li.id,
                                              delivered_quantity=Decimal('200')))
    dr2.line_items.append(DeliveryReceiptItem(line_number=1, sales_order_item_id=li.id,
                                              delivered_quantity=Decimal('150')))
    db_session.commit()
    result = get_order_monitoring(b, date(2026, 7, 1), date(2026, 7, 31))
    out_li = result['customers'][0]['sales_orders'][0]['line_items'][0]
    assert out_li['dr_qty'] == 350.0
    assert [d['dr_number'] for d in out_li['deliveries']] == ['DR-MON-0004', 'DR-MON-0005']
    assert [d['quantity'] for d in out_li['deliveries']] == [200.0, 150.0]
    assert sum(d['quantity'] for d in out_li['deliveries']) == out_li['dr_qty']
