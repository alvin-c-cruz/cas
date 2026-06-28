import pytest
from app import db
from app.sales_orders.models import SalesOrder
from app.sales_orders.views import generate_so_number
pytestmark = pytest.mark.usefixtures("app")


def test_first_number_format(db_session):
    n = generate_so_number()
    assert n.startswith('SO-') and n.endswith('-0001') and len(n.split('-')) == 4


def test_increments_within_month(db_session, main_branch):
    from datetime import date
    from app.customers.models import Customer
    c = Customer(code='C001', name='C'); db.session.add(c); db.session.commit()
    n1 = generate_so_number()
    db.session.add(SalesOrder(so_number=n1, order_date=date.today(), customer_id=c.id,
                              customer_name='C', branch_id=main_branch.id))
    db.session.commit()
    assert generate_so_number() != n1   # next suffix
