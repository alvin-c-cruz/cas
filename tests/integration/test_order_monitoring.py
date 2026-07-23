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
         'order_date': date(2026, 7, 5), 'status': 'confirmed', 'line_items': [],
         'delivery_receipts': []},
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
