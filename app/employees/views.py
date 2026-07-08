"""Employee master views (opt-in payroll module)."""
from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user
from functools import wraps
from app import db
from app.employees.models import Employee
from app.employees.forms import EmployeeForm
from app.employees.utils import generate_next_employee_no
from app.audit.utils import log_create, log_update, log_delete, model_to_dict
from app.users.utils import get_accessible_branches
from app.users.models import User

employees_bp = Blueprint('employees', __name__, template_folder='templates')


def _wants_json():
    """True when the request is an AJAX/JSON call (modal quick-add)."""
    return (
        request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        or request.accept_mimetypes.best == 'application/json'
    )

_FIELDS = ['employee_no', 'first_name', 'middle_name', 'last_name', 'birthdate',
           'address', 'phone', 'email', 'tin', 'sss_no', 'philhealth_no', 'pagibig_no',
           'date_hired', 'employment_status', 'position', 'branch_id', 'tax_status_code',
           'qualified_dependents', 'is_minimum_wage', 'pay_basis', 'basic_rate',
           'pay_frequency', 'user_id', 'is_active']


def staff_or_above_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('users.login'))
        if current_user.role not in ['staff', 'accountant', 'admin', 'chief_accountant']:
            flash('You do not have permission to perform this action.', 'error')
            return redirect(url_for('dashboard.index'))
        return f(*args, **kwargs)
    return wrapper


def _set_choices(form):
    branches = get_accessible_branches(current_user)
    form.branch_id.choices = [(b.id, f'{b.code} - {b.name}') for b in branches]
    users = User.query.filter_by(is_active=True).order_by(User.username).all()
    form.user_id.choices = [('', '— none —')] + [(u.id, f'{u.username}') for u in users]


def _apply(form, e):
    e.employee_no = form.employee_no.data
    e.first_name = form.first_name.data
    e.middle_name = form.middle_name.data
    e.last_name = form.last_name.data
    e.birthdate = form.birthdate.data
    e.address = form.address.data
    e.phone = form.phone.data
    e.email = form.email.data
    e.tin = form.tin.data
    e.sss_no = form.sss_no.data
    e.philhealth_no = form.philhealth_no.data
    e.pagibig_no = form.pagibig_no.data
    e.date_hired = form.date_hired.data
    e.employment_status = form.employment_status.data or None
    e.position = form.position.data
    e.branch_id = form.branch_id.data
    e.tax_status_code = form.tax_status_code.data
    e.qualified_dependents = form.qualified_dependents.data or 0
    e.is_minimum_wage = bool(form.is_minimum_wage.data)
    e.pay_basis = form.pay_basis.data or None
    e.basic_rate = form.basic_rate.data
    e.pay_frequency = form.pay_frequency.data or None
    e.user_id = form.user_id.data or None
    e.is_active = form.is_active.data == '1'


@employees_bp.route('/employees')
@login_required
def list_employees():
    q = (request.args.get('q') or '').strip()
    query = Employee.query
    if q:
        like = f'%{q}%'
        query = query.filter(db.or_(Employee.employee_no.ilike(like),
                                    Employee.first_name.ilike(like),
                                    Employee.last_name.ilike(like)))
    employees = query.order_by(Employee.employee_no).all()
    return render_template('employees/list.html', employees=employees, search_query=q)


@employees_bp.route('/employees/create', methods=['GET', 'POST'])
@login_required
@staff_or_above_required
def create():
    form = EmployeeForm()
    _set_choices(form)
    if form.validate_on_submit():
        if Employee.query.filter_by(employee_no=form.employee_no.data).first():
            msg = f'Employee number "{form.employee_no.data}" already exists.'
            if _wants_json():
                return jsonify(ok=False, errors={'employee_no': msg}), 422
            flash(msg, 'error')
            return render_template('employees/form.html', form=form, employee=None)
        e = Employee()
        _apply(form, e)
        db.session.add(e); db.session.commit()
        log_create(module='employee', record_id=e.id,
                   record_identifier=f'{e.employee_no} - {e.full_name}',
                   new_values=model_to_dict(e, _FIELDS))
        if _wants_json():
            return jsonify(ok=True, employee={
                'id': e.id,
                'label': f'{e.employee_no} - {e.full_name}',
            })
        flash(f'Employee "{e.full_name}" created successfully!', 'success')
        return redirect(url_for('employees.list_employees'))
    if request.method == 'POST' and _wants_json():
        return jsonify(ok=False, errors={f: errs[0] for f, errs in form.errors.items()}), 422
    if request.method == 'GET':
        form.employee_no.data = generate_next_employee_no()
        form.is_active.data = '1'
    return render_template('employees/form.html', form=form, employee=None)


@employees_bp.route('/employees/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@staff_or_above_required
def edit(id):
    e = db.get_or_404(Employee, id)
    form = EmployeeForm(obj=e)
    _set_choices(form)
    if form.validate_on_submit():
        dup = Employee.query.filter(Employee.employee_no == form.employee_no.data,
                                    Employee.id != id).first()
        if dup:
            flash(f'Employee number "{form.employee_no.data}" already exists.', 'error')
            return render_template('employees/form.html', form=form, employee=e)
        old = model_to_dict(e, _FIELDS)
        _apply(form, e)
        db.session.commit()
        log_update(module='employee', record_id=e.id,
                   record_identifier=f'{e.employee_no} - {e.full_name}',
                   old_values=old, new_values=model_to_dict(e, _FIELDS))
        flash(f'Employee "{e.full_name}" updated successfully!', 'success')
        return redirect(url_for('employees.list_employees'))
    if request.method == 'GET':
        form.is_active.data = '1' if e.is_active else '0'
        form.user_id.data = e.user_id or ''
    return render_template('employees/form.html', form=form, employee=e)


@employees_bp.route('/employees/<int:id>/toggle-status', methods=['POST'])
@login_required
@staff_or_above_required
def toggle_status(id):
    e = db.get_or_404(Employee, id)
    old = model_to_dict(e, ['is_active'])
    e.is_active = not e.is_active
    db.session.commit()
    log_update(module='employee', record_id=e.id,
               record_identifier=f'{e.employee_no} - {e.full_name}',
               old_values=old, new_values=model_to_dict(e, ['is_active']))
    flash(f'Employee "{e.full_name}" is now {"Active" if e.is_active else "Inactive"}.', 'success')
    return redirect(url_for('employees.list_employees'))


@employees_bp.route('/employees/<int:id>/delete', methods=['POST'])
@login_required
@staff_or_above_required
def delete(id):
    e = db.get_or_404(Employee, id)
    # Delete guard - SQLite FK enforcement is off app-wide; block if referenced by an
    # AP voucher. The polymorphic payee columns land in Phase 2 (Task 6); until then
    # no AP row can reference an employee, so hasattr() keeps this a safe no-op that
    # auto-activates once the columns exist - no later switch needed.
    from app.accounts_payable.models import AccountsPayable
    if hasattr(AccountsPayable, 'payee_type'):
        refs = AccountsPayable.query.filter_by(payee_type='employee', payee_id=e.id).count()
    else:
        refs = 0
    if refs > 0:
        flash(f'Cannot delete "{e.full_name}": {refs} voucher(s) reference this employee.', 'error')
        return redirect(url_for('employees.list_employees'))
    old = model_to_dict(e, _FIELDS)
    ident = f'{e.employee_no} - {e.full_name}'; eid = e.id; name = e.full_name
    db.session.delete(e); db.session.commit()
    log_delete(module='employee', record_id=eid, record_identifier=ident, old_values=old)
    flash(f'Employee "{name}" deleted successfully!', 'success')
    return redirect(url_for('employees.list_employees'))
