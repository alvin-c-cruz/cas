import pytest
from datetime import date
from app import db
from app.employees.models import Employee
from app.sales_orders.models import SalesOrder, copy_salesperson

pytestmark = [pytest.mark.integration, pytest.mark.sales_orders]


def _emp(db_session, branch_id):
    e = Employee(employee_no='E-001', first_name='Jane', last_name='Cruz',
                 branch_id=branch_id, is_active=True)
    db_session.add(e); db_session.commit()
    return e


def test_so_salesperson_fk_and_to_dict(db_session, main_branch):
    e = _emp(db_session, main_branch.id)
    so = SalesOrder(so_number='SO-SP-1', order_date=date(2026, 7, 8), customer_id=1,
                    customer_name='Acme', branch_id=main_branch.id, salesperson_id=e.id)
    db_session.add(so); db_session.commit()
    assert so.salesperson.full_name == 'Jane Cruz'
    d = so.to_dict()
    assert d['salesperson_id'] == e.id and d['salesperson_name'] == 'Jane Cruz'
    so2 = SalesOrder(so_number='SO-SP-2', order_date=date(2026, 7, 8), customer_id=1,
                     customer_name='Acme', branch_id=main_branch.id)
    db_session.add(so2); db_session.commit()
    assert so2.to_dict()['salesperson_name'] is None


def test_copy_salesperson(db_session, main_branch):
    e = _emp(db_session, main_branch.id)
    src = SalesOrder(so_number='SO-SP-3', order_date=date(2026, 7, 8), customer_id=1,
                     customer_name='Acme', branch_id=main_branch.id, salesperson_id=e.id)
    dst = SalesOrder(so_number='SO-SP-4', order_date=date(2026, 7, 8), customer_id=1,
                     customer_name='Acme', branch_id=main_branch.id)
    copy_salesperson(src, dst)
    assert dst.salesperson_id == e.id
