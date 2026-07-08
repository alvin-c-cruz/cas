from app import db
from app.employees.models import Employee
from app.vendors.models import Vendor


def test_create_form_lists_vendors_and_employees(client, admin_user, main_branch, login_user):
    login_user(client, 'admin', 'admin123')
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = main_branch.id
    db.session.add(Vendor(code='V001', name='Anthropic', is_active=True))
    db.session.add(Employee(employee_no='EMP-0001', first_name='Alvin', last_name='Cruz',
                            branch_id=main_branch.id))
    db.session.commit()
    html = client.get('/accounts-payable/create').get_data(as_text=True)
    assert 'value="vendor:' in html
    assert 'value="employee:' in html
    assert 'Select Payee' in html   # payee step relabelled
