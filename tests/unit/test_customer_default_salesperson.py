"""Customer.default_salesperson_id (BUG-CUSTOMER-NO-DEFAULT-SALESPERSON)."""
import pytest
from app import db

pytestmark = [pytest.mark.integration, pytest.mark.customers]


def test_customer_default_salesperson_defaults_to_none(db_session):
    from app.customers.models import Customer
    c = Customer(code='CUST-DS-0001', name='Test Co')
    db.session.add(c); db.session.commit()
    assert c.default_salesperson_id is None
    assert c.default_salesperson is None


def test_customer_default_salesperson_relationship(db_session, main_branch):
    from app.customers.models import Customer
    from app.employees.models import Employee
    emp = Employee(employee_no='EMP-DS-001', first_name='Juan', last_name='Cruz',
                   branch_id=main_branch.id, is_active=True, is_salesperson=True)
    db.session.add(emp); db.session.commit()
    c = Customer(code='CUST-DS-0002', name='Test Co 2', default_salesperson_id=emp.id)
    db.session.add(c); db.session.commit()
    assert c.default_salesperson_id == emp.id
    assert c.default_salesperson.full_name == emp.full_name
