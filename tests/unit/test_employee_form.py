from werkzeug.datastructures import MultiDict
from app.employees.forms import EmployeeForm


def _formdata(**over):
    data = {
        'employee_no': 'EMP-0001', 'first_name': 'Alvin', 'last_name': 'Cruz',
        'branch_id': '1', 'is_active': '1', 'qualified_dependents': '0',
    }
    data.update(over)
    return MultiDict(data)


def test_valid_minimal(app):
    with app.test_request_context():
        form = EmployeeForm(formdata=_formdata(), meta={'csrf': False})
        form.branch_id.choices = [(1, 'MAIN')]
        form.user_id.choices = [('', '— none —')]
        assert form.validate() is True


def test_requires_first_and_last_name(app):
    with app.test_request_context():
        form = EmployeeForm(formdata=_formdata(first_name='', last_name=''), meta={'csrf': False})
        form.branch_id.choices = [(1, 'MAIN')]
        form.user_id.choices = [('', '— none —')]
        assert form.validate() is False
        assert 'first_name' in form.errors and 'last_name' in form.errors
