from app import db
from app.employees.models import Employee
from app.audit.models import AuditLog


def test_create_employee_and_audit(client, admin_user, branch_manila, login_user):
    login_user(client, 'admin', 'admin123')
    resp = client.post('/employees/create', data={
        'employee_no': 'EMP-0001', 'first_name': 'Alvin', 'last_name': 'Cruz',
        'branch_id': str(branch_manila.id), 'is_active': '1', 'qualified_dependents': '0',
        'user_id': '',
    }, follow_redirects=True)
    assert resp.status_code == 200
    e = Employee.query.filter_by(employee_no='EMP-0001').first()
    assert e is not None and e.full_name == 'Alvin Cruz'
    assert AuditLog.query.filter_by(module='employee', action='create', record_id=e.id).count() == 1


def test_toggle_status(client, admin_user, branch_manila, login_user):
    login_user(client, 'admin', 'admin123')
    e = Employee(employee_no='EMP-0002', first_name='M', last_name='S', branch_id=branch_manila.id)
    db.session.add(e); db.session.commit()
    client.post(f'/employees/{e.id}/toggle-status', follow_redirects=True)
    db.session.refresh(e)
    assert e.is_active is False
