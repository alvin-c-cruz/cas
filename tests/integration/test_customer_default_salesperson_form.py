"""Customer create/edit form default-salesperson picker (BUG-CUSTOMER-NO-DEFAULT-SALESPERSON)."""
import pytest
from app import db

pytestmark = [pytest.mark.integration, pytest.mark.customers]


def _login(client, user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True


def test_create_form_renders_salesperson_choices(client, db_session, admin_user, main_branch):
    from app.employees.models import Employee
    emp = Employee(employee_no='EMP-DS-010', first_name='Ana', last_name='Reyes',
                   branch_id=main_branch.id, is_active=True, is_salesperson=True)
    db.session.add(emp); db.session.commit()
    _login(client, admin_user)
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = main_branch.id
    resp = client.get('/customers/create')
    body = resp.get_data(as_text=True)
    assert 'name="default_salesperson_id"' in body
    assert 'Reyes' in body


def test_create_persists_default_salesperson(client, db_session, admin_user, main_branch):
    from app.employees.models import Employee
    from app.customers.models import Customer
    emp = Employee(employee_no='EMP-DS-011', first_name='Ben', last_name='Santos',
                   branch_id=main_branch.id, is_active=True, is_salesperson=True)
    db.session.add(emp); db.session.commit()
    _login(client, admin_user)
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = main_branch.id
    resp = client.post('/customers/create', data={
        'code': 'CUST-DS-0010', 'name': 'Persist Co', 'payment_terms': 'Net 30',
        'is_active': '1', 'default_salesperson_id': str(emp.id),
    }, follow_redirects=False)
    customer = Customer.query.filter_by(code='CUST-DS-0010').first()
    assert customer is not None
    assert customer.default_salesperson_id == emp.id


def test_create_allows_blank_default_salesperson(client, db_session, admin_user, main_branch):
    from app.customers.models import Customer
    _login(client, admin_user)
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = main_branch.id
    resp = client.post('/customers/create', data={
        'code': 'CUST-DS-0011', 'name': 'No Salesperson Co', 'payment_terms': 'Net 30',
        'is_active': '1', 'default_salesperson_id': '',
    }, follow_redirects=False)
    customer = Customer.query.filter_by(code='CUST-DS-0011').first()
    assert customer is not None
    assert customer.default_salesperson_id is None
