import pytest
from app import db
from app.sales_orders.models import SalesOrder
from app.sales_orders.views import generate_so_number
pytestmark = [pytest.mark.usefixtures("app"), pytest.mark.sales_orders]


def test_first_number_format(db_session):
    n = generate_so_number()
    assert n == '00001'


def test_increments_within_month(db_session, main_branch):
    from datetime import date
    from app.customers.models import Customer
    c = Customer(code='C001', name='C'); db.session.add(c); db.session.commit()
    n1 = generate_so_number()
    db.session.add(SalesOrder(so_number=n1, order_date=date.today(), customer_id=c.id,
                              customer_name='C', branch_id=main_branch.id))
    db.session.commit()
    assert generate_so_number() == '00002'


def test_ignores_legacy_prefixed_numbers(db_session, main_branch):
    from datetime import date
    from app.customers.models import Customer
    c = Customer(code='C002', name='C'); db.session.add(c); db.session.commit()
    db.session.add(SalesOrder(so_number='SO-2026-07-0030', order_date=date.today(),
                              customer_id=c.id, customer_name='C', branch_id=main_branch.id))
    db.session.commit()
    assert generate_so_number() == '00001'
