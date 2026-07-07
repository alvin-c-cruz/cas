# Employee Master + Combined Payee Dropdown Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a branch-scoped, opt-in Employee master to CAS and a combined vendor+employee payee picker on the AP voucher, with employee-payee vouchers segregated out of vendor/BIR-supplier reports.

**Architecture:** New `app/employees/` blueprint mirrors `app/vendors/`. `AccountsPayable` gains a polymorphic payee (`payee_type` + `payee_id`); `vendor_id` is made nullable and kept populated only for vendor payees (NULL for employees), so existing vendor-scoped reports exclude employees automatically. The APV form's vendor select becomes a combined payee select whose option values encode `type:id`.

**Tech Stack:** Flask, SQLAlchemy 2.0 spellings, Flask-WTF/WTForms, Flask-Migrate (Alembic, hand-written batch migrations), Jinja2, Choices.js (`initSearchSelect`), pytest.

## Global Constraints

- **Model changes need explicit user approval before writing the model / migrating.** This plan IS the proposal; do not start Task 1's model step until the user signs off on the plan.
- **TDD:** write the failing test first, watch it fail, implement minimally, watch it pass, commit.
- **SQLAlchemy 2.0 only:** `db.session.get(Model, id)` / `db.get_or_404(Model, id)`. Never `Model.query.get(...)`.
- **PH time:** timestamps use `ph_now` from `app.utils`; never naive `datetime.now()`.
- **Audit every write:** `log_create` / `log_update` / `log_delete` from `app.audit.utils`; CRUD tests assert the audit row.
- **Migrations are hand-written with `op.batch_alter_table`** (Migrate is configured without `render_as_batch`). Generate the empty revision with `flask db revision -m "..."` (correct `down_revision`), then hand-fill. Verify constraint/column changes on a **copy of a real `cas.db`**, not just conftest `create_all()`.
- **Master-data UI verbs:** launch button "Create Employee"; in-form submit "Create"/"Update". **No empty-state CTA.**
- **No hardcoded styling** — design tokens only; responsive. **No JS `confirm/alert/prompt`** — HTML modals with `{{ csrf_token() }}`.
- **`Employee.position` is free-form HR text** — never a dropdown of user roles, never derived from `User.role`.
- Run tasks from `projects/cas/`. Use the project venv: `C:/envs/erp-workspace/projects/cas/venv/Scripts/python -m pytest ...`.

---

## PHASE 1 — Employee master (self-contained; ships on its own)

### Task 1: `Employee` model + migration

**Files:**
- Create: `app/employees/__init__.py` (empty)
- Create: `app/employees/models.py`
- Modify: `app/__init__.py` (import `Employee` in the model-import block)
- Create: `migrations/versions/<rev>_create_employees.py` (via `flask db revision`)
- Test: `tests/unit/test_employee_model.py`

**Interfaces:**
- Produces: `app.employees.models.Employee` with columns per the spec; `full_name` property; `to_dict()` (columns only); `branch` relationship.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_employee_model.py
import pytest
from app import db
from app.employees.models import Employee
from app.branches.models import Branch


def _branch():
    b = Branch(code='MAIN', name='Head Office')
    db.session.add(b); db.session.commit()
    return b


def test_employee_minimal_create(db_session):
    b = _branch()
    e = Employee(employee_no='EMP-0001', first_name='Alvin', last_name='Cruz', branch_id=b.id)
    db.session.add(e); db.session.commit()
    assert e.id is not None
    assert e.is_active is True                 # default
    assert e.qualified_dependents == 0         # default
    assert e.is_minimum_wage is False          # default


def test_full_name_collapses_blank_middle(db_session):
    b = _branch()
    e = Employee(employee_no='EMP-0002', first_name='Maria', middle_name=None,
                 last_name='Santos', branch_id=b.id)
    db.session.add(e); db.session.commit()
    assert e.full_name == 'Maria Santos'


def test_employee_no_unique(db_session):
    b = _branch()
    db.session.add(Employee(employee_no='EMP-0003', first_name='A', last_name='B', branch_id=b.id))
    db.session.commit()
    db.session.add(Employee(employee_no='EMP-0003', first_name='C', last_name='D', branch_id=b.id))
    with pytest.raises(Exception):
        db.session.commit()
    db.session.rollback()


def test_to_dict_is_columns_only(db_session):
    b = _branch()
    e = Employee(employee_no='EMP-0004', first_name='A', last_name='B', branch_id=b.id, user_id=None)
    db.session.add(e); db.session.commit()
    d = e.to_dict()
    assert d['employee_no'] == 'EMP-0004'
    assert d['user_id'] is None
    assert 'branch' not in d                    # no relationship reads
```

- [ ] **Step 2: Run to verify it fails**

Run: `venv/Scripts/python -m pytest tests/unit/test_employee_model.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.employees'`.

- [ ] **Step 3: Create the model**

```python
# app/employees/__init__.py
```
(empty file)

```python
# app/employees/models.py
"""Employee master (payroll foundation). Branch-scoped, opt-in module."""
from app import db
from app.utils import ph_now


class Employee(db.Model):
    __tablename__ = 'employees'

    id = db.Column(db.Integer, primary_key=True)

    # Identity
    employee_no = db.Column(db.String(20), unique=True, nullable=False, index=True)
    first_name = db.Column(db.String(100), nullable=False)
    middle_name = db.Column(db.String(100))
    last_name = db.Column(db.String(100), nullable=False)
    birthdate = db.Column(db.Date)
    address = db.Column(db.Text)
    phone = db.Column(db.String(50))
    email = db.Column(db.String(120))

    # Government IDs
    tin = db.Column(db.String(50))
    sss_no = db.Column(db.String(50))
    philhealth_no = db.Column(db.String(50))
    pagibig_no = db.Column(db.String(50))

    # Employment
    date_hired = db.Column(db.Date)
    employment_status = db.Column(db.String(30))   # regular/probationary/contractual/part-time
    position = db.Column(db.String(120))           # free-form HR title; NOT a user role

    # Branch scope (branch-scoping rule)
    branch_id = db.Column(db.Integer, db.ForeignKey('branches.id'), nullable=False, index=True)
    branch = db.relationship('Branch', foreign_keys=[branch_id])

    # Tax
    tax_status_code = db.Column(db.String(10))
    qualified_dependents = db.Column(db.Integer, default=0)
    is_minimum_wage = db.Column(db.Boolean, default=False)

    # Compensation
    pay_basis = db.Column(db.String(20))           # monthly/daily
    basic_rate = db.Column(db.Numeric(12, 2))
    pay_frequency = db.Column(db.String(20))       # monthly/semi-monthly

    # Optional identity link to a login (pure identity mapping; no role/position meaning)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True, index=True)
    user = db.relationship('User', foreign_keys=[user_id])

    is_active = db.Column(db.Boolean, default=True, nullable=False)

    created_at = db.Column(db.DateTime, default=ph_now, nullable=False)
    updated_at = db.Column(db.DateTime, default=ph_now, onupdate=ph_now, nullable=False)

    def __repr__(self):
        return f'<Employee {self.employee_no} - {self.full_name}>'

    @property
    def full_name(self):
        parts = [self.first_name, self.middle_name, self.last_name]
        return ' '.join(p for p in parts if p)

    def to_dict(self):
        return {
            'id': self.id,
            'employee_no': self.employee_no,
            'first_name': self.first_name,
            'middle_name': self.middle_name,
            'last_name': self.last_name,
            'full_name': self.full_name,
            'birthdate': self.birthdate.isoformat() if self.birthdate else None,
            'address': self.address,
            'phone': self.phone,
            'email': self.email,
            'tin': self.tin,
            'sss_no': self.sss_no,
            'philhealth_no': self.philhealth_no,
            'pagibig_no': self.pagibig_no,
            'date_hired': self.date_hired.isoformat() if self.date_hired else None,
            'employment_status': self.employment_status,
            'position': self.position,
            'branch_id': self.branch_id,
            'tax_status_code': self.tax_status_code,
            'qualified_dependents': self.qualified_dependents,
            'is_minimum_wage': self.is_minimum_wage,
            'pay_basis': self.pay_basis,
            'basic_rate': float(self.basic_rate) if self.basic_rate is not None else None,
            'pay_frequency': self.pay_frequency,
            'user_id': self.user_id,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
```

Add the import to the model-import block in `app/__init__.py` (near the other
`from app.<x>.models import ...` lines used for migration autodetect):

```python
    from app.employees.models import Employee  # noqa: F401
```

- [ ] **Step 4: Run to verify the model tests pass**

Run: `venv/Scripts/python -m pytest tests/unit/test_employee_model.py -v`
Expected: PASS (conftest `create_all()` builds the new table).

- [ ] **Step 5: Generate + hand-write the migration**

```bash
venv/Scripts/flask db revision -m "create employees table"
```
Open the generated `migrations/versions/<rev>_create_employees.py` and fill:

```python
def upgrade():
    op.create_table(
        'employees',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('employee_no', sa.String(length=20), nullable=False),
        sa.Column('first_name', sa.String(length=100), nullable=False),
        sa.Column('middle_name', sa.String(length=100), nullable=True),
        sa.Column('last_name', sa.String(length=100), nullable=False),
        sa.Column('birthdate', sa.Date(), nullable=True),
        sa.Column('address', sa.Text(), nullable=True),
        sa.Column('phone', sa.String(length=50), nullable=True),
        sa.Column('email', sa.String(length=120), nullable=True),
        sa.Column('tin', sa.String(length=50), nullable=True),
        sa.Column('sss_no', sa.String(length=50), nullable=True),
        sa.Column('philhealth_no', sa.String(length=50), nullable=True),
        sa.Column('pagibig_no', sa.String(length=50), nullable=True),
        sa.Column('date_hired', sa.Date(), nullable=True),
        sa.Column('employment_status', sa.String(length=30), nullable=True),
        sa.Column('position', sa.String(length=120), nullable=True),
        sa.Column('branch_id', sa.Integer(), nullable=False),
        sa.Column('tax_status_code', sa.String(length=10), nullable=True),
        sa.Column('qualified_dependents', sa.Integer(), nullable=True),
        sa.Column('is_minimum_wage', sa.Boolean(), nullable=True),
        sa.Column('pay_basis', sa.String(length=20), nullable=True),
        sa.Column('basic_rate', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('pay_frequency', sa.String(length=20), nullable=True),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['branch_id'], ['branches.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('employees', schema=None) as batch_op:
        batch_op.create_index('ix_employees_employee_no', ['employee_no'], unique=True)
        batch_op.create_index('ix_employees_branch_id', ['branch_id'], unique=False)
        batch_op.create_index('ix_employees_user_id', ['user_id'], unique=False)


def downgrade():
    with op.batch_alter_table('employees', schema=None) as batch_op:
        batch_op.drop_index('ix_employees_user_id')
        batch_op.drop_index('ix_employees_branch_id')
        batch_op.drop_index('ix_employees_employee_no')
    op.drop_table('employees')
```

- [ ] **Step 6: Verify the migration on a copy of the real DB**

```bash
cp instance/cas.db /tmp/cas_migtest.db
SQLALCHEMY_DATABASE_URI=sqlite:////tmp/cas_migtest.db venv/Scripts/flask db upgrade
venv/Scripts/python -c "import sqlite3;c=sqlite3.connect('/tmp/cas_migtest.db');print(c.execute(\"SELECT name FROM sqlite_master WHERE type='table' AND name='employees'\").fetchall());print([r[1] for r in c.execute('PRAGMA index_list(employees)')])"
```
Expected: `[('employees',)]` printed, and an index list containing `ix_employees_employee_no` (unique).

- [ ] **Step 7: Commit**

```bash
git add app/employees/__init__.py app/employees/models.py app/__init__.py migrations/versions/ tests/unit/test_employee_model.py
git commit -m "feat(employees): Employee master model + migration"
```

---

### Task 2: `employee_no` generator

**Files:**
- Create: `app/employees/utils.py`
- Test: `tests/unit/test_employee_utils.py`

**Interfaces:**
- Produces: `generate_next_employee_no() -> str` returning `EMP-####` (4-wide), sequenced by numeric suffix.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_employee_utils.py
from app import db
from app.employees.models import Employee
from app.employees.utils import generate_next_employee_no
from app.branches.models import Branch


def _mk(no):
    b = Branch(code='MAIN', name='HO'); db.session.add(b); db.session.flush()
    db.session.add(Employee(employee_no=no, first_name='X', last_name='Y', branch_id=b.id))
    db.session.commit()


def test_first_code(db_session):
    assert generate_next_employee_no() == 'EMP-0001'


def test_sequences_by_numeric_suffix_past_9999(db_session):
    _mk('EMP-9999')
    assert generate_next_employee_no() == 'EMP-10000'


def test_ignores_non_conforming(db_session):
    _mk('LEGACY-1')
    assert generate_next_employee_no() == 'EMP-0001'
```

- [ ] **Step 2: Run to verify it fails**

Run: `venv/Scripts/python -m pytest tests/unit/test_employee_utils.py -v`
Expected: FAIL — `ModuleNotFoundError: app.employees.utils`.

- [ ] **Step 3: Implement (mirror `generate_next_vendor_code`)**

```python
# app/employees/utils.py
"""Employee helpers."""


def generate_next_employee_no():
    """Next EMP-#### by numeric suffix (not lexicographic — 'EMP-9999' < 'EMP-10000')."""
    from app.employees.models import Employee
    codes = [e.employee_no for e in Employee.query.filter(Employee.employee_no.like('EMP-%')).all()]
    max_number = 0
    for code in codes:
        try:
            max_number = max(max_number, int(code.split('-', 1)[1]))
        except (ValueError, IndexError):
            continue
    return f'EMP-{max_number + 1:04d}'
```

- [ ] **Step 4: Run to verify it passes**

Run: `venv/Scripts/python -m pytest tests/unit/test_employee_utils.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/employees/utils.py tests/unit/test_employee_utils.py
git commit -m "feat(employees): employee_no generator"
```

---

### Task 3: `EmployeeForm`

**Files:**
- Create: `app/employees/forms.py`
- Test: `tests/unit/test_employee_form.py`

**Interfaces:**
- Produces: `EmployeeForm` with fields `employee_no, first_name, middle_name, last_name, birthdate, address, phone, email, tin, sss_no, philhealth_no, pagibig_no, date_hired, employment_status, position, branch_id (SelectField coerce=int), tax_status_code, qualified_dependents, is_minimum_wage (BooleanField), pay_basis, basic_rate (DecimalField), pay_frequency, user_id (SelectField coerce, Optional), is_active (SelectField '1'/'0')`.

- [ ] **Step 1: Write the failing test** (WTForms unit test feeds **formdata** MultiDict, per `wtforms-test-formdata-not-data`)

```python
# tests/unit/test_employee_form.py
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
```

- [ ] **Step 2: Run to verify it fails**

Run: `venv/Scripts/python -m pytest tests/unit/test_employee_form.py -v`
Expected: FAIL — `ModuleNotFoundError: app.employees.forms`.

- [ ] **Step 3: Implement**

```python
# app/employees/forms.py
"""Forms for Employee master."""
from flask_wtf import FlaskForm
from wtforms import (StringField, TextAreaField, DateField, SelectField,
                     IntegerField, DecimalField, BooleanField)
from wtforms.validators import DataRequired, Length, Optional, Email, NumberRange


class EmployeeForm(FlaskForm):
    employee_no = StringField('Employee No.', validators=[
        DataRequired(message='Employee number is required.'),
        Length(max=20)])
    first_name = StringField('First Name', validators=[DataRequired(), Length(max=100)])
    middle_name = StringField('Middle Name', validators=[Optional(), Length(max=100)])
    last_name = StringField('Last Name', validators=[DataRequired(), Length(max=100)])
    birthdate = DateField('Birthdate', validators=[Optional()], format='%Y-%m-%d')
    address = TextAreaField('Address', validators=[Optional()])
    phone = StringField('Phone', validators=[Optional(), Length(max=50)])
    email = StringField('Email', validators=[Optional(), Email(), Length(max=120)])

    tin = StringField('TIN', validators=[Optional(), Length(max=50)])
    sss_no = StringField('SSS No.', validators=[Optional(), Length(max=50)])
    philhealth_no = StringField('PhilHealth No.', validators=[Optional(), Length(max=50)])
    pagibig_no = StringField('Pag-IBIG No.', validators=[Optional(), Length(max=50)])

    date_hired = DateField('Date Hired', validators=[Optional()], format='%Y-%m-%d')
    employment_status = SelectField('Employment Status', validators=[Optional()], choices=[
        ('', '— select —'), ('regular', 'Regular'), ('probationary', 'Probationary'),
        ('contractual', 'Contractual'), ('part-time', 'Part-time')])
    position = StringField('Position (HR title)', validators=[Optional(), Length(max=120)])

    branch_id = SelectField('Branch', coerce=int, validators=[
        DataRequired(message='Branch is required.')])

    tax_status_code = StringField('Tax Status Code', validators=[Optional(), Length(max=10)])
    qualified_dependents = IntegerField('Qualified Dependents', validators=[
        Optional(), NumberRange(min=0)], default=0)
    is_minimum_wage = BooleanField('Minimum-Wage Earner')

    pay_basis = SelectField('Pay Basis', validators=[Optional()], choices=[
        ('', '— select —'), ('monthly', 'Monthly'), ('daily', 'Daily')])
    basic_rate = DecimalField('Basic Rate', validators=[Optional(), NumberRange(min=0)], places=2)
    pay_frequency = SelectField('Pay Frequency', validators=[Optional()], choices=[
        ('', '— select —'), ('monthly', 'Monthly'), ('semi-monthly', 'Semi-monthly')])

    # Optional identity link. Choices set in the view: [('', '— none —'), (user.id, label), ...]
    user_id = SelectField('Linked User (optional)', validators=[Optional()], coerce=lambda v: int(v) if v else None)

    is_active = SelectField('Status', choices=[('1', 'Active'), ('0', 'Inactive')])
```

- [ ] **Step 4: Run to verify it passes**

Run: `venv/Scripts/python -m pytest tests/unit/test_employee_form.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/employees/forms.py tests/unit/test_employee_form.py
git commit -m "feat(employees): EmployeeForm"
```

---

### Task 4: Employee CRUD views, templates, blueprint registration

**Files:**
- Create: `app/employees/views.py`
- Create: `app/employees/templates/employees/list.html`
- Create: `app/employees/templates/employees/form.html`
- Modify: `app/__init__.py` (register `employees_bp`)
- Test: `tests/integration/test_employees_crud.py`

**Interfaces:**
- Consumes: `Employee`, `generate_next_employee_no`, `EmployeeForm`, `log_create/log_update/log_delete`, `get_accessible_branches` (`app.users.utils`).
- Produces: blueprint `employees` with endpoints `employees.list_employees`, `employees.create`, `employees.edit`, `employees.toggle_status`, `employees.delete`.

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_employees_crud.py
from app import db
from app.employees.models import Employee
from app.audit.models import AuditLog


def _login(client, u): 
    from tests.conftest import login_user
    login_user(client, u)


def test_create_employee_and_audit(client, admin_user, branch_manila):
    _login(client, admin_user)
    resp = client.post('/employees/create', data={
        'employee_no': 'EMP-0001', 'first_name': 'Alvin', 'last_name': 'Cruz',
        'branch_id': str(branch_manila.id), 'is_active': '1', 'qualified_dependents': '0',
        'user_id': '',
    }, follow_redirects=True)
    assert resp.status_code == 200
    e = Employee.query.filter_by(employee_no='EMP-0001').first()
    assert e is not None and e.full_name == 'Alvin Cruz'
    assert AuditLog.query.filter_by(module='employee', action='create', record_id=e.id).count() == 1


def test_toggle_status(client, admin_user, branch_manila):
    _login(client, admin_user)
    e = Employee(employee_no='EMP-0002', first_name='M', last_name='S', branch_id=branch_manila.id)
    db.session.add(e); db.session.commit()
    client.post(f'/employees/{e.id}/toggle-status', follow_redirects=True)
    db.session.refresh(e)
    assert e.is_active is False
```

(Adjust `login_user`, `admin_user`, `branch_manila` to the real fixture names in
`tests/conftest.py`; `branch_manila` exists per the CAS testing notes.)

- [ ] **Step 2: Run to verify it fails**

Run: `venv/Scripts/python -m pytest tests/integration/test_employees_crud.py -v`
Expected: FAIL — 404 (no `employees` blueprint).

- [ ] **Step 3: Implement views** (mirror `app/vendors/views.py`; branch choices via `get_accessible_branches`)

```python
# app/employees/views.py
"""Employee master views (opt-in payroll module)."""
from flask import Blueprint, render_template, redirect, url_for, flash, request
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
            flash(f'Employee number "{form.employee_no.data}" already exists.', 'error')
            return render_template('employees/form.html', form=form, employee=None)
        e = Employee()
        _apply(form, e)
        db.session.add(e); db.session.commit()
        log_create(module='employee', record_id=e.id,
                   record_identifier=f'{e.employee_no} - {e.full_name}',
                   new_values=model_to_dict(e, _FIELDS))
        flash(f'Employee "{e.full_name}" created successfully!', 'success')
        return redirect(url_for('employees.list_employees'))
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
    # Delete guard — SQLite FK enforcement is off app-wide; block if referenced by an AP voucher.
    from app.accounts_payable.models import AccountsPayable
    refs = AccountsPayable.query.filter_by(payee_type='employee', payee_id=e.id).count()
    if refs > 0:
        flash(f'Cannot delete "{e.full_name}": {refs} voucher(s) reference this employee.', 'error')
        return redirect(url_for('employees.list_employees'))
    old = model_to_dict(e, _FIELDS)
    ident = f'{e.employee_no} - {e.full_name}'; eid = e.id; name = e.full_name
    db.session.delete(e); db.session.commit()
    log_delete(module='employee', record_id=eid, record_identifier=ident, old_values=old)
    flash(f'Employee "{name}" deleted successfully!', 'success')
    return redirect(url_for('employees.list_employees'))
```

> NOTE: the delete guard references `AccountsPayable.payee_type`/`payee_id`, added
> in Task 6. Until Task 6 lands, that filter matches zero rows harmlessly (the
> columns don't exist yet → guard the import behind Task 6). If executing Phase 1
> alone first, temporarily filter `AccountsPayable.query.filter_by(vendor_id=e.id)`
> and switch to `payee_type/payee_id` in Task 6, Step 6.

Register the blueprint in `app/__init__.py` (blueprint-registration block):

```python
    from app.employees.views import employees_bp
    app.register_blueprint(employees_bp)
```

- [ ] **Step 4: Create templates** (mirror `app/vendors/templates/vendors/list.html` and `form.html`)

`list.html`: extend the base, page title "Employees", a top-right **"Create Employee"**
link to `employees.create`, a search box, and a table (Employee No., Name, Position,
Branch, Status badge, Actions: edit pencil + `status_toggle()` macro). **No
empty-state CTA** — a plain `<tr><td colspan=...>No employees found.</td></tr>` when
`employees` is empty. Import macros: `{% from 'macros.html' import status_toggle %}`
and call `initStatusToggle()`; reuse global `.badge-active`/`.badge-inactive`.

`form.html`: sections Identity / Government IDs / Employment / Tax / Compensation /
Link, using design tokens. Submit button reads **"Create"** (new) / **"Update"**
(edit). Branch and Linked-User selects use `initSearchSelect` (`": "` separator).
Include `{{ form.hidden_tag() }}` for CSRF. Follow the exact field/label/error markup
pattern from `vendors/form.html`.

- [ ] **Step 5: Run to verify it passes**

Run: `venv/Scripts/python -m pytest tests/integration/test_employees_crud.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/employees/views.py app/employees/templates app/__init__.py tests/integration/test_employees_crud.py
git commit -m "feat(employees): CRUD views + templates + blueprint"
```

---

### Task 5: Register Employees as an opt-in module

**Files:**
- Modify: `app/users/module_access.py` (add registry entry)
- Test: `tests/integration/test_employees_module_gate.py`

**Interfaces:**
- Consumes: `MODULE_REGISTRY`, `module_enabled`, `can_access_module`.
- Produces: module key `'employees'` (optional, `default_enabled=False`, area `Payroll`).

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_employees_module_gate.py
from app.users.module_access import module_enabled, MODULE_REGISTRY


def test_employees_registered_optional_default_off(app):
    entry = next((m for m in MODULE_REGISTRY if m['key'] == 'employees'), None)
    assert entry is not None
    assert entry['optional'] is True
    assert entry.get('default_enabled') is False
    assert entry['area'] == 'Payroll'


def test_employees_disabled_by_default(app):
    with app.app_context():
        assert module_enabled('employees') is False
```

- [ ] **Step 2: Run to verify it fails**

Run: `venv/Scripts/python -m pytest tests/integration/test_employees_module_gate.py -v`
Expected: FAIL — entry is None.

- [ ] **Step 3: Add the registry entry** (append inside `MODULE_REGISTRY`, in the Maintenance group)

```python
    {'key': 'employees', 'label': 'Employees', 'section': 'Maintenance',
     'area': 'Payroll', 'group': 'Masters',
     'optional': True, 'depends_on': [], 'default_enabled': False,
     'endpoints': ('employees.',)},
```

Also add `employees.create` to `EXEMPT_ENDPOINTS` so a user with a transaction
module (but not the Employees module) can still inline-quick-add from the AP form:

```python
EXEMPT_ENDPOINTS = {'vendors.create', 'vendors.vendor_defaults', 'employees.create'}
```

- [ ] **Step 4: Run to verify it passes**

Run: `venv/Scripts/python -m pytest tests/integration/test_employees_module_gate.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/users/module_access.py tests/integration/test_employees_module_gate.py
git commit -m "feat(employees): register opt-in Payroll module"
```

**PHASE 1 CHECKPOINT:** Employee master ships independently here. Employees can be
created/edited/toggled; the module is off by default and enabled per instance.

---

## PHASE 2 — Polymorphic payee on `AccountsPayable`

### Task 6: Add `payee_type` / `payee_id`; make `vendor_id` nullable; backfill

**Files:**
- Modify: `app/accounts_payable/models.py:43-44` (payee columns; vendor_id nullable)
- Create: `migrations/versions/<rev>_ap_polymorphic_payee.py`
- Test: `tests/unit/test_ap_payee_model.py`, `tests/integration/test_ap_payee_migration.py`

**Interfaces:**
- Produces: `AccountsPayable.payee_type` (`'vendor'`|`'employee'`, NOT NULL default `'vendor'`), `AccountsPayable.payee_id` (Integer, NOT NULL). `vendor_id` now nullable.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_ap_payee_model.py
from datetime import date
from decimal import Decimal
from app import db
from app.accounts_payable.models import AccountsPayable


def _ap(**over):
    base = dict(ap_number='AP-X-1', ap_date=date(2026, 6, 30), due_date=date(2026, 7, 30),
                vendor_name='X', notes='n', payee_type='vendor', payee_id=1, vendor_id=1)
    base.update(over)
    return AccountsPayable(**base)


def test_employee_payee_has_null_vendor_id(db_session):
    ap = _ap(ap_number='AP-X-2', payee_type='employee', payee_id=5, vendor_id=None)
    db.session.add(ap); db.session.commit()
    assert ap.vendor_id is None
    assert ap.payee_type == 'employee' and ap.payee_id == 5


def test_payee_type_default_vendor(db_session):
    ap = AccountsPayable(ap_number='AP-X-3', ap_date=date(2026, 6, 30), due_date=date(2026, 7, 30),
                         vendor_name='X', notes='n', payee_id=1, vendor_id=1)
    db.session.add(ap); db.session.commit()
    assert ap.payee_type == 'vendor'
```

- [ ] **Step 2: Run to verify it fails**

Run: `venv/Scripts/python -m pytest tests/unit/test_ap_payee_model.py -v`
Expected: FAIL — `TypeError: 'payee_type' is an invalid keyword argument`.

- [ ] **Step 3: Modify the model** (`app/accounts_payable/models.py`, the vendor block at lines 42-44)

```python
    # Payee reference (polymorphic: vendor OR employee)
    payee_type = db.Column(db.String(20), nullable=False, default='vendor', server_default='vendor', index=True)
    payee_id = db.Column(db.Integer, nullable=False, default=0)

    # Vendor reference — nullable now; set for vendor payees, NULL for employees.
    vendor_id = db.Column(db.Integer, db.ForeignKey('vendors.id'), nullable=True, index=True)
    vendor = db.relationship('Vendor', backref='accounts_payable')
```

- [ ] **Step 4: Run to verify the model unit test passes**

Run: `venv/Scripts/python -m pytest tests/unit/test_ap_payee_model.py -v`
Expected: PASS.

- [ ] **Step 5: Generate + hand-write the migration (batch; backfill)**

```bash
venv/Scripts/flask db revision -m "ap polymorphic payee"
```
Fill:

```python
def upgrade():
    with op.batch_alter_table('accounts_payable', schema=None) as batch_op:
        batch_op.add_column(sa.Column('payee_type', sa.String(length=20),
                                      nullable=False, server_default='vendor'))
        batch_op.add_column(sa.Column('payee_id', sa.Integer(), nullable=False, server_default='0'))
        batch_op.alter_column('vendor_id', existing_type=sa.Integer(), nullable=True)
        batch_op.create_index('ix_accounts_payable_payee_type', ['payee_type'], unique=False)
    # Backfill: existing rows are all vendor payees.
    op.execute("UPDATE accounts_payable SET payee_type='vendor', payee_id=vendor_id "
               "WHERE payee_id=0 OR payee_id IS NULL")


def downgrade():
    with op.batch_alter_table('accounts_payable', schema=None) as batch_op:
        batch_op.drop_index('ix_accounts_payable_payee_type')
        batch_op.alter_column('vendor_id', existing_type=sa.Integer(), nullable=False)
        batch_op.drop_column('payee_id')
        batch_op.drop_column('payee_type')
```

- [ ] **Step 6: Write + run the backfill verification test on a real-DB copy**

```python
# tests/integration/test_ap_payee_migration.py
"""Run manually against a copy of instance/cas.db (see command below)."""
```
Run:
```bash
cp instance/cas.db /tmp/cas_ap_mig.db
SQLALCHEMY_DATABASE_URI=sqlite:////tmp/cas_ap_mig.db venv/Scripts/flask db upgrade
venv/Scripts/python -c "import sqlite3;c=sqlite3.connect('/tmp/cas_ap_mig.db');\
print(c.execute('SELECT count(*) FROM accounts_payable WHERE payee_type IS NULL OR payee_id IS NULL').fetchone());\
print(c.execute('SELECT count(*) FROM accounts_payable WHERE payee_type=\"vendor\" AND payee_id<>vendor_id').fetchone())"
```
Expected: both counts `(0,)` — every existing row backfilled to `payee_type='vendor'`, `payee_id=vendor_id`, `vendor_id` preserved.

Also switch the Task 4 delete guard to the real filter now:
`AccountsPayable.query.filter_by(payee_type='employee', payee_id=e.id)`.

- [ ] **Step 7: Commit**

```bash
git add app/accounts_payable/models.py migrations/versions/ app/employees/views.py tests/unit/test_ap_payee_model.py tests/integration/test_ap_payee_migration.py
git commit -m "feat(ap): polymorphic payee columns + backfill migration"
```

---

### Task 7: `payee` resolver + `vendor` back-compat + `to_dict`

**Files:**
- Modify: `app/accounts_payable/models.py` (add `payee` property, adjust `to_dict`)
- Test: `tests/unit/test_ap_payee_resolver.py`

**Interfaces:**
- Produces: `AccountsPayable.payee` -> `Vendor` when `payee_type=='vendor'` else `Employee` (or None); `to_dict()` gains `payee_type`, `payee_id`, `payee_name`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_ap_payee_resolver.py
from datetime import date
from app import db
from app.accounts_payable.models import AccountsPayable
from app.employees.models import Employee
from app.vendors.models import Vendor
from app.branches.models import Branch


def test_payee_resolves_vendor(db_session):
    v = Vendor(code='V001', name='Anthropic'); db.session.add(v); db.session.commit()
    ap = AccountsPayable(ap_number='AP-R-1', ap_date=date(2026, 6, 1), due_date=date(2026, 7, 1),
                         vendor_name='Anthropic', notes='n', payee_type='vendor', payee_id=v.id, vendor_id=v.id)
    db.session.add(ap); db.session.commit()
    assert ap.payee.id == v.id
    assert ap.to_dict()['payee_name'] == 'Anthropic'


def test_payee_resolves_employee(db_session):
    b = Branch(code='MAIN', name='HO'); db.session.add(b); db.session.commit()
    e = Employee(employee_no='EMP-0001', first_name='Alvin', last_name='Cruz', branch_id=b.id)
    db.session.add(e); db.session.commit()
    ap = AccountsPayable(ap_number='AP-R-2', ap_date=date(2026, 6, 1), due_date=date(2026, 7, 1),
                         vendor_name='Alvin Cruz', notes='n', payee_type='employee', payee_id=e.id, vendor_id=None)
    db.session.add(ap); db.session.commit()
    assert ap.payee.id == e.id
    assert ap.to_dict()['payee_name'] == 'Alvin Cruz'
    assert ap.vendor is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `venv/Scripts/python -m pytest tests/unit/test_ap_payee_resolver.py -v`
Expected: FAIL — `AttributeError: payee` / KeyError `payee_name`.

- [ ] **Step 3: Implement** (add to `AccountsPayable`)

```python
    @property
    def payee(self):
        """Resolve the polymorphic payee to its Vendor or Employee row (or None)."""
        if self.payee_type == 'employee':
            from app.employees.models import Employee
            return db.session.get(Employee, self.payee_id) if self.payee_id else None
        from app.vendors.models import Vendor
        return db.session.get(Vendor, self.payee_id) if self.payee_id else None

    @property
    def payee_display_name(self):
        p = self.payee
        if p is None:
            return self.vendor_name          # historical snapshot fallback
        return p.full_name if self.payee_type == 'employee' else p.name
```

In `to_dict` add (after `'vendor_id': self.vendor_id,`):

```python
            'payee_type': self.payee_type,
            'payee_id': self.payee_id,
            'payee_name': self.payee_display_name,
```

- [ ] **Step 4: Run to verify it passes**

Run: `venv/Scripts/python -m pytest tests/unit/test_ap_payee_resolver.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/accounts_payable/models.py tests/unit/test_ap_payee_resolver.py
git commit -m "feat(ap): payee resolver + payee_name in to_dict"
```

---

### Task 8: AP create/edit views resolve payee (vendor or employee)

**Files:**
- Modify: `app/accounts_payable/views.py` (create ~628-738; edit ~900-990: choices, payee resolution, snapshot, per-type defaults)
- Modify: `app/accounts_payable/forms.py:33-35` (replace `vendor_id` field with a `payee` string field)
- Test: `tests/integration/test_ap_create_employee_payee.py`

**Interfaces:**
- Consumes: `Employee`, `Vendor`, `payee` resolver.
- Produces: AP create/edit accept a `payee` value formatted `"vendor:<id>"` or `"employee:<id>"`, set `payee_type`/`payee_id`, snapshot the name, and NULL `vendor_id` for employees.

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_ap_create_employee_payee.py
from app import db
from app.accounts_payable.models import AccountsPayable
from app.employees.models import Employee


def test_create_ap_with_employee_payee(client, admin_user, branch_manila, db_with_data):
    from tests.conftest import login_user
    login_user(client, admin_user)
    e = Employee(employee_no='EMP-0001', first_name='Alvin', last_name='Cruz', branch_id=branch_manila.id)
    db.session.add(e); db.session.commit()
    resp = client.post('/accounts-payable/create', data={
        'ap_number': 'AP-2026-06-9001', 'ap_date': '2026-06-30', 'due_date': '2026-07-30',
        'payee': f'employee:{e.id}', 'payment_terms': 'Net 30', 'notes': 'Salary for June 2026',
        'line_items': '[]',   # adjust to the real line_items JSON shape used by the form
    }, follow_redirects=True)
    assert resp.status_code == 200
    ap = AccountsPayable.query.filter_by(ap_number='AP-2026-06-9001').first()
    assert ap is not None
    assert ap.payee_type == 'employee' and ap.payee_id == e.id
    assert ap.vendor_id is None
    assert ap.vendor_name == 'Alvin Cruz'
```

(Populate `line_items` with a valid single-line payload matching
`_build_validated_ap_lines()`; copy the shape from an existing AP integration test.)

- [ ] **Step 2: Run to verify it fails**

Run: `venv/Scripts/python -m pytest tests/integration/test_ap_create_employee_payee.py -v`
Expected: FAIL — form has no `payee` field / `payee_type` not set.

- [ ] **Step 3a: Swap the form field** (`app/accounts_payable/forms.py`, replace the `vendor_id` SelectField at lines 33-35)

```python
    # Combined payee: "vendor:<id>" or "employee:<id>". Parsed in the view.
    payee = StringField('Payee', validators=[
        DataRequired(message='Payee is required.')
    ])
```
(Remove the now-unused `SelectField` import if nothing else needs it.)

- [ ] **Step 3b: Resolve the payee in `create`** — replace the vendor-choices line and vendor lookup. Instead of `form.vendor_id.choices = ...`, build a helper and use it in both create and edit:

```python
# near the other module-level helpers in views.py
def _parse_payee(raw):
    """'vendor:12' | 'employee:3' -> (payee_type, payee_id) or (None, None)."""
    try:
        kind, sid = (raw or '').split(':', 1)
        if kind in ('vendor', 'employee'):
            return kind, int(sid)
    except (ValueError, AttributeError):
        pass
    return None, None


def _resolve_payee(payee_type, payee_id):
    """Return the Vendor/Employee row, or None."""
    if payee_type == 'employee':
        from app.employees.models import Employee
        return db.session.get(Employee, payee_id)
    return db.session.get(Vendor, payee_id)
```

In `create`, delete lines 635-636 (`vendors = ...` / `form.vendor_id.choices = ...`).
Replace the vendor lookup block (lines 673-676) with:

```python
            payee_type, payee_id = _parse_payee(request.form.get('payee'))
            payee = _resolve_payee(payee_type, payee_id)
            if payee is None:
                flash('Selected payee not found.', 'error')
                return _render_form(request.form.get('line_items', ''))
            is_vendor = payee_type == 'vendor'
```

Replace the `AccountsPayable(...)` snapshot args (lines 701-704) with:

```python
                payee_type=payee_type,
                payee_id=payee_id,
                vendor_id=(payee.id if is_vendor else None),
                vendor_name=(payee.name if is_vendor else payee.full_name),
                vendor_tin=(payee.tin if hasattr(payee, 'tin') else None),
                vendor_address=(payee.address if is_vendor else payee.address),
```

Guard the duplicate-vendor-invoice check (lines 678-688) with `if is_vendor and inv_num:`
(employees have no vendor-invoice concept). Wrap the vendor-defaults autofill likewise.

- [ ] **Step 3c: Mirror the same changes in `edit`** (~lines 900-990): same `_parse_payee`/`_resolve_payee`, same snapshot assignment, and pre-select the current payee on GET by passing `current_payee=f'{ap.payee_type}:{ap.payee_id}'` to the template.

- [ ] **Step 4: Run to verify it passes**

Run: `venv/Scripts/python -m pytest tests/integration/test_ap_create_employee_payee.py -v`
Expected: PASS. Also run the existing AP suite to catch regressions:
`venv/Scripts/python -m pytest tests/integration -k accounts_payable -v` — all green.

- [ ] **Step 5: Commit**

```bash
git add app/accounts_payable/views.py app/accounts_payable/forms.py tests/integration/test_ap_create_employee_payee.py
git commit -m "feat(ap): resolve combined payee (vendor or employee) in create/edit"
```

---

## PHASE 3 — Combined dropdown UI

### Task 9: Combined payee `<select>` on the AP form

**Files:**
- Modify: `app/accounts_payable/views.py` (`_render_form` + edit render: pass `vendors` and `employees` lists)
- Modify: `app/accounts_payable/templates/accounts_payable/form.html:37-67` (payee select), JS block (~1040-1165: change listener parses `type:id`)
- Test: `tests/integration/test_ap_payee_dropdown.py`

**Interfaces:**
- Consumes: `Vendor` (active), `Employee` (active).
- Produces: a `#payee` select whose `<option value>` is `vendor:<id>` / `employee:<id>`, badged by type.

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_ap_payee_dropdown.py
from app import db
from app.employees.models import Employee
from app.vendors.models import Vendor


def test_create_form_lists_vendors_and_employees(client, admin_user, branch_manila):
    from tests.conftest import login_user
    login_user(client, admin_user)
    db.session.add(Vendor(code='V001', name='Anthropic'))
    db.session.add(Employee(employee_no='EMP-0001', first_name='Alvin', last_name='Cruz', branch_id=branch_manila.id))
    db.session.commit()
    html = client.get('/accounts-payable/create').get_data(as_text=True)
    assert 'value="vendor:' in html
    assert 'value="employee:' in html
    assert 'STEP 1' in html  # payee step present
```

- [ ] **Step 2: Run to verify it fails**

Run: `venv/Scripts/python -m pytest tests/integration/test_ap_payee_dropdown.py -v`
Expected: FAIL — no `employee:` options.

- [ ] **Step 3a: Pass both lists from the view.** In `_render_form` (and the edit
render), add:

```python
        vendors = Vendor.query.filter_by(is_active=True).order_by(Vendor.code).all()
        from app.employees.models import Employee
        employees = Employee.query.filter_by(is_active=True).order_by(Employee.employee_no).all()
```
and pass `vendors=vendors, employees=employees, current_payee=current_payee` to
`render_template` (default `current_payee=''` on create).

- [ ] **Step 3b: Replace the vendor `<select>`** in `form.html` (lines 37-67). Keep
the STEP-1 wrapper; swap the options to a combined, badged list. Use the `": "`
separator convention:

```html
<select name="payee" id="payee" class="form-control" required
        data-search-select data-placeholder="Search or select a payee…">
    <option value=""></option>
    {% for v in vendors %}
        <option value="vendor:{{ v.id }}"
            {% if current_payee == 'vendor:' ~ v.id %}selected{% endif %}>
            {{ v.code }} : {{ v.name }} [Vendor]
        </option>
    {% endfor %}
    {% for e in employees %}
        <option value="employee:{{ e.id }}"
            {% if current_payee == 'employee:' ~ e.id %}selected{% endif %}>
            {{ e.employee_no }} : {{ e.full_name }} [Employee]
        </option>
    {% endfor %}
</select>
```
Relabel the section heading "STEP 1 — SELECT VENDOR" → "STEP 1 — SELECT PAYEE".

- [ ] **Step 3c: Update the JS** (`form.html`, ~1040-1165). The old code reads
`document.getElementById('vendor_id')`. Rename the reference to `payee`, and in the
change handler parse the value: `const [kind, id] = e.target.value.split(':')`.
When `kind === 'vendor'`, keep the existing vendor-defaults autofill (call
`/vendors/<id>/defaults`). When `kind === 'employee'`, **skip** the vendor-defaults
call and set each new line's VT to "No VAT" and WT to "None" (mirrors the manual
salary booking). Update `initVendorId`/`initVendorSel` names accordingly. Bump the
`?v=N` on any edited static asset link.

- [ ] **Step 4: Run to verify it passes**

Run: `venv/Scripts/python -m pytest tests/integration/test_ap_payee_dropdown.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/accounts_payable/views.py app/accounts_payable/templates/accounts_payable/form.html
git commit -m "feat(ap): combined vendor+employee payee dropdown"
```

---

### Task 10: Inline "Add Employee" + payee surfaces on detail/list/print

**Files:**
- Modify: `app/accounts_payable/templates/accounts_payable/form.html` (Add Employee quick-add modal)
- Modify: `app/accounts_payable/templates/accounts_payable/{list,detail,print}.html` (show payee name + type badge)
- Modify: `app/employees/views.py` (`create` returns JSON on `X-Requested-With`, mirroring `vendors.create`)
- Test: `tests/integration/test_employee_quick_add.py`

**Interfaces:**
- Consumes: `employees.create` (JSON mode), `_wants_json()` pattern from vendors.
- Produces: quick-add employee returns `{ok, employee: {id, label}}`; AP surfaces render `ap.payee_display_name` with a `[Vendor]`/`[Employee]` badge.

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_employee_quick_add.py
from app.employees.models import Employee


def test_quick_add_employee_returns_json(client, admin_user, branch_manila):
    from tests.conftest import login_user
    login_user(client, admin_user)
    resp = client.post('/employees/create',
                       data={'employee_no': 'EMP-0001', 'first_name': 'Alvin', 'last_name': 'Cruz',
                             'branch_id': str(branch_manila.id), 'is_active': '1',
                             'qualified_dependents': '0', 'user_id': ''},
                       headers={'X-Requested-With': 'XMLHttpRequest'})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body['ok'] is True
    assert body['employee']['label'].startswith('EMP-0001')
    assert Employee.query.count() == 1
```

- [ ] **Step 2: Run to verify it fails**

Run: `venv/Scripts/python -m pytest tests/integration/test_employee_quick_add.py -v`
Expected: FAIL — HTML redirect, not JSON.

- [ ] **Step 3: Add JSON mode to `employees.create`** (mirror `vendors.create`'s
`_wants_json()`): on success return
`jsonify(ok=True, employee={'id': e.id, 'label': f'{e.employee_no} - {e.full_name}'})`;
on validation error return `jsonify(ok=False, errors={...}), 422`. Add the
`_wants_json()` helper to `employees/views.py` (copy from vendors). Then add an
"✚ Add Employee" button + hidden HTML modal (CSRF token, no JS `confirm`) next to
the existing quick-add in `form.html`, POSTing to `employees.create` and inserting
the returned option into `#payee`. In `list.html`/`detail.html`/`print.html`, render
`ap.payee_display_name` and a badge derived from `ap.payee_type` (SI-surface
consistency: same jargon across list/detail/print).

- [ ] **Step 4: Run to verify it passes**

Run: `venv/Scripts/python -m pytest tests/integration/test_employee_quick_add.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/employees/views.py app/accounts_payable/templates
git commit -m "feat(ap): inline Add Employee + payee-type surfaces"
```

---

## PHASE 4 — Segregation from vendor/BIR reports

### Task 11: Exclude employee-payee vouchers from vendor/BIR-supplier reports

**Files:**
- Modify: report queries in `app/reports/` (AP aging, BIR purchases, supplier Alphalist) and the AP list vendor filter (`app/accounts_payable/views.py:519`)
- Test: `tests/integration/test_payee_segregation.py`

**Interfaces:**
- Consumes: `AccountsPayable.payee_type` / `vendor_id`.
- Produces: every vendor-scoped report filters `AccountsPayable.payee_type == 'vendor'` (equivalently `vendor_id.isnot(None)`).

- [ ] **Step 1: Locate the queries**

Run: `grep -rn "AccountsPayable" app/reports/ | grep -iE "aging|purchase|alphalist"`
and inspect `reports.ap_aging`, `reports.bir_purchases`, `reports.bir_alphalist`.

- [ ] **Step 2: Write the failing test**

```python
# tests/integration/test_payee_segregation.py
from datetime import date
from app import db
from app.accounts_payable.models import AccountsPayable
from app.employees.models import Employee
from app.vendors.models import Vendor


def _post_ap(payee_type, payee_id, vendor_id, name, num):
    ap = AccountsPayable(ap_number=num, ap_date=date(2026, 6, 30), due_date=date(2026, 7, 30),
                         vendor_name=name, notes='n', status='posted',
                         payee_type=payee_type, payee_id=payee_id, vendor_id=vendor_id,
                         subtotal=1000, total_amount=1000, balance=1000)
    db.session.add(ap); db.session.commit(); return ap


def test_employee_ap_absent_from_ap_aging(client, admin_user, branch_manila):
    from tests.conftest import login_user
    login_user(client, admin_user)
    v = Vendor(code='V001', name='Anthropic'); db.session.add(v); db.session.commit()
    e = Employee(employee_no='EMP-0001', first_name='Alvin', last_name='Cruz', branch_id=branch_manila.id)
    db.session.add(e); db.session.commit()
    _post_ap('vendor', v.id, v.id, 'Anthropic', 'AP-SEG-V')
    _post_ap('employee', e.id, None, 'Alvin Cruz', 'AP-SEG-E')
    html = client.get('/reports/ap-aging?date_from=2026-01-01&date_to=2026-12-31').get_data(as_text=True)
    assert 'Anthropic' in html
    assert 'Alvin Cruz' not in html      # employee payee segregated out
```

(Add analogous assertions for `/reports/bir/purchases` and `/reports/bir/alphalist`
using the real endpoint paths found in Step 1.)

- [ ] **Step 3: Run to verify it fails**

Run: `venv/Scripts/python -m pytest tests/integration/test_payee_segregation.py -v`
Expected: FAIL — 'Alvin Cruz' appears in AP aging.

- [ ] **Step 4: Add the filter** to each vendor-scoped query. Where a report joins or
groups `AccountsPayable` by vendor, add:

```python
    .filter(AccountsPayable.payee_type == 'vendor')
```

For the AP list vendor filter (`views.py:519`), the existing `filter_by(vendor_id=...)`
already excludes employees (their `vendor_id` is NULL); leave it. Confirm the
unfiltered list still shows both (with the badge from Task 10).

- [ ] **Step 5: Run to verify it passes**

Run: `venv/Scripts/python -m pytest tests/integration/test_payee_segregation.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/reports tests/integration/test_payee_segregation.py
git commit -m "feat(reports): segregate employee-payee vouchers from vendor/BIR reports"
```

---

### Task 12: Full-suite + guard gate

**Files:** none (verification only)

- [ ] **Step 1: Run the AP + employees + reports subset**

Run: `venv/Scripts/python -m pytest tests/ -k "employee or accounts_payable or payee or aging or bir or segregation" -q`
Expected: all PASS, 0 warnings introduced.

- [ ] **Step 2: Run the full suite** (user-triggered per project rule — ask the user to run `/run-tests cas`, or run pytest directly and report raw results). Expected: no NEW failures vs. the baseline.

- [ ] **Step 3: Guard the AP blast radius**

Ask the user to run `/guard cas` (pre-push regression gate). Expected: no newly-broken
"done" modules vs. baseline. Fix any breakage before finishing.

- [ ] **Step 4: Final commit / handoff** — nothing to commit if clean; summarize the
staged commits and confirm the module is opt-in (off by default).

---

## Self-Review (completed while writing)

- **Spec coverage:** Employee model (T1) · numbering (T2) · form (T3) · CRUD+templates (T4) · opt-in module (T5) · polymorphic payee + backfill (T6) · resolver/to_dict (T7) · payee resolution in views (T8) · combined dropdown (T9) · inline add + surfaces (T10) · segregation (T11) · guard (T12). All spec sections mapped.
- **Non-derivation rule:** `position` is a free-form `StringField` (T3) — never a role dropdown. ✔
- **Type consistency:** `_parse_payee`/`_resolve_payee` (T8) reused in T9; `payee_display_name` defined in T7 and used in T10/T11; `payee` value format `type:id` consistent across T8/T9. ✔
- **Migration discipline:** both migrations hand-written with `op.batch_alter_table`, verified on a real-DB copy (T1 S6, T6 S6). ✔
- **Known follow-through:** T4's delete guard references T6 columns — flagged with the temporary-filter note and switched in T6 S6.
