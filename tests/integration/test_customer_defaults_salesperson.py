"""customer_defaults() includes default_salesperson_id (BUG-CUSTOMER-NO-DEFAULT-SALESPERSON)."""
import pytest
from app import db

pytestmark = [pytest.mark.integration]


def _login(client, user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True


def test_customer_defaults_endpoint_includes_salesperson(client, db_session, admin_user, main_branch):
    from app.customers.models import Customer
    from app.employees.models import Employee
    emp = Employee(employee_no='EMP-DS-020', first_name='Cora', last_name='Diaz',
                   branch_id=main_branch.id, is_active=True, is_salesperson=True)
    db.session.add(emp); db.session.commit()
    customer = Customer(code='CUST-DS-0020', name='Defaults Co', default_salesperson_id=emp.id)
    db.session.add(customer); db.session.commit()
    _login(client, admin_user)
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = main_branch.id
    resp = client.get(f'/customers/{customer.id}/defaults')
    data = resp.get_json()
    assert data['default_salesperson_id'] == emp.id


def test_customer_defaults_endpoint_null_when_no_default_salesperson(client, db_session, admin_user, main_branch):
    from app.customers.models import Customer
    customer = Customer(code='CUST-DS-0021', name='No Default Co')
    db.session.add(customer); db.session.commit()
    _login(client, admin_user)
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = main_branch.id
    resp = client.get(f'/customers/{customer.id}/defaults')
    data = resp.get_json()
    assert data['default_salesperson_id'] is None
