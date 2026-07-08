import pytest
from datetime import date
from app import db
from app.sales_orders.models import SalesOrder
from app.sales_orders.monitoring import get_order_monitoring

pytestmark = [pytest.mark.integration, pytest.mark.sales_orders]

_TODAY = date(2026, 7, 8)


def _so(db_session, branch_id, n, status, order_date, expected=None, customer='Acme'):
    so = SalesOrder(so_number=f'SO-MON-{n:04d}', order_date=order_date, customer_id=1,
                    customer_name=customer, branch_id=branch_id, status=status,
                    expected_delivery_date=expected)
    db_session.add(so); db_session.commit()
    return so


def test_metrics_counts_buckets_and_branch_isolation(db_session, main_branch, branch_manila):
    b = main_branch.id
    # three confirmed (open) orders
    _so(db_session, b, 1, 'confirmed', date(2026, 7, 5), date(2026, 7, 1), 'Acme')   # overdue, aging 0-7
    _so(db_session, b, 2, 'confirmed', date(2026, 6, 20), date(2026, 7, 10), 'Acme')  # due_soon, aging 8-30
    _so(db_session, b, 3, 'confirmed', date(2026, 5, 1), None, 'Beta')                # aging 60+
    _so(db_session, b, 4, 'draft', date(2026, 7, 7))
    _so(db_session, b, 5, 'cancelled', date(2026, 7, 7))
    # another branch's confirmed order must NOT leak in
    _so(db_session, branch_manila.id, 6, 'confirmed', date(2026, 7, 1), date(2026, 7, 1))

    m = get_order_monitoring(b, _TODAY)
    assert m['cards'] == {'open': 3, 'drafts': 1, 'overdue': 1, 'due_soon': 1}
    assert m['by_status'] == {'labels': ['Draft', 'Confirmed', 'Cancelled'], 'data': [1, 3, 1]}
    assert m['aging'] == {'labels': ['0-7', '8-30', '31-60', '60+'], 'data': [1, 1, 0, 1]}
    assert m['top_customers'] == [{'customer_name': 'Acme', 'count': 2},
                                  {'customer_name': 'Beta', 'count': 1}]
