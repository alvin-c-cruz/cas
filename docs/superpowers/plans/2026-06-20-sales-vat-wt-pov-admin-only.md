# Sales VAT Categories + WT Seller POV + Admin-Only Tax Maintenance — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split VAT maintenance into a purchase table (`VATCategory`) and a new sales table (`SalesVATCategory` with a `transaction_nature` classifier), give Withholding Tax a seller-POV `sales_name`, and lock all VAT + WT maintenance to admins with an admin-to-admin approval workflow.

**Architecture:** New `SalesVATCategory` blueprint mirrors the existing `vat_categories` blueprint (Approach A — two separate models). Sales documents (SI/CRV) and the customer form repoint to the sales table; purchase documents (AP/CDV) and the vendor form stay on `VATCategory`. The split is sequenced so the app works at every commit: add the sales table first, rewire consumers, *then* drop `VATCategory.output_vat_account_id`. Access on all three modules changes from `accountant_or_admin` to `admin`-only; the auto-approve rule changes from sole-accountant to sole-admin.

**Tech Stack:** Flask, SQLAlchemy, Flask-Migrate/Alembic, WTForms, Flask-Caching (SimpleCache), pytest, SQLite.

## Global Constraints

- **Spec:** `docs/superpowers/specs/2026-06-20-sales-vat-wt-pov-admin-only-design.md` — source of truth.
- **Model changes already signed off** in the spec (per CLAUDE.md gate). Do not introduce model fields beyond those in Section 1 without new approval.
- **TDD mandatory** — write the failing test first, watch it fail, implement minimally, watch it pass, commit. (`superpowers:test-driven-development`.)
- **Audit every write** — every create/update/delete view test asserts an `AuditLog` row with correct `action`, `record`, actor.
- **Time:** use `ph_now` / `app.utils` helpers, never naive `datetime.now()`.
- **No JS popups** — delete/confirm modals are HTML with `{{ csrf_token() }}`.
- **No hardcoded styling** — design tokens / `style.css` only.
- **Cache invalidation** — after mutating sales VAT rows, call `clear_sales_vat_cache()`.
- **Static cache-buster** — if any file under `app/static/` is edited, bump `?v=N` on every `<link>`/`<script>` that loads it.
- **Commits:** work on `main`, auto-commit each task, **do not push** unless asked.
- **`transaction_nature` enum values (verbatim):** `regular`, `zero_export`, `zero_other`, `exempt`, `government`. Default `regular`.
- **Sales VAT seed codes (verbatim):** `SVAT-G`, `SVAT-S`, `SVAT-EX`, `SVAT-ZR`, `SVAT-GOV`.
- **Two seed paths** must stay in lockstep: `app/fixtures.py` AND `app/seeds/seed_data.py`.
- **Output VAT account** = code `2100` ("Output Tax"); **Input VAT** = `1200` ("Input Tax").
- **Test login (conftest fixtures):** the per-role user fixtures use password `<username>123` — `admin`/`admin123`, `accountant`/`accountant123`, `staff`/`staff123`, `viewer`/`viewer123`. In example `_login(client, user)` helpers below, derive it as `user.username + '123'` (NOT a literal placeholder). When a test creates an *extra* user, `set_password('<known>')` and log in with that exact value.

---

## Phase 1 — Sales VAT model + blueprint (purely additive; app keeps working)

### Task 1: `SalesVATCategory` + `SalesVATCategoryChangeRequest` models

**Files:**
- Create: `app/sales_vat_categories/__init__.py` (empty package marker)
- Create: `app/sales_vat_categories/models.py`
- Test: `tests/unit/test_sales_vat_category_model.py`

**Interfaces:**
- Produces: `SalesVATCategory` (columns: `id, code, name, description, rate, transaction_nature, output_vat_account_id, is_active, created_at, created_by_id, updated_at, updated_by_id`; `.to_dict()`), `SalesVATCategoryChangeRequest` (mirror of `VATCategoryChangeRequest` with `sales_vat_category_id` FK).

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_sales_vat_category_model.py
from decimal import Decimal
from app.sales_vat_categories.models import SalesVATCategory, SalesVATCategoryChangeRequest


class TestSalesVATCategoryModel:
    def test_create_and_to_dict(self, db_session):
        cat = SalesVATCategory(code='SVAT-G', name='Sale of Goods (12%)',
                               rate=Decimal('12.00'), transaction_nature='regular',
                               is_active=True)
        db_session.add(cat)
        db_session.commit()
        d = cat.to_dict()
        assert d['code'] == 'SVAT-G'
        assert d['rate'] == 12.0
        assert d['transaction_nature'] == 'regular'
        assert d['is_active'] is True

    def test_transaction_nature_defaults_regular(self, db_session):
        cat = SalesVATCategory(code='SVAT-X', name='X', rate=Decimal('12.00'))
        db_session.add(cat)
        db_session.commit()
        assert cat.transaction_nature == 'regular'

    def test_change_request_persists(self, db_session, admin_user):
        cr = SalesVATCategoryChangeRequest(action='create', status='pending',
                                           proposed_data='{"code": "SVAT-G"}',
                                           requested_by_id=admin_user.id)
        db_session.add(cr)
        db_session.commit()
        assert cr.id is not None
        assert cr.status == 'pending'
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_sales_vat_category_model.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.sales_vat_categories'`

- [ ] **Step 3: Create the package marker and models**

Create `app/sales_vat_categories/__init__.py` (empty file).

Create `app/sales_vat_categories/models.py` — mirror `app/vat_categories/models.py` with these differences: table names `sales_vat_categories` / `sales_vat_category_change_requests`; **no `input_vat_account_id`**; **add `transaction_nature`**; FK/backref names use `sales_vat_category`. Full content:

```python
"""
Sales VAT Category models (output/sales side) for Philippine BIR compliance.
Purchase-side categories live in app.vat_categories (VATCategory).
"""
from app import db
from app.utils import ph_now


class SalesVATCategory(db.Model):
    """Sales (output) VAT Category master table (shared across branches)."""
    __tablename__ = 'sales_vat_categories'

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    rate = db.Column(db.Numeric(5, 2), nullable=False)  # e.g., 12.00 for 12%
    # BIR sales classifier: regular / zero_export / zero_other / exempt / government
    transaction_nature = db.Column(db.String(30), nullable=False, default='regular')
    # Output VAT account used for sales journal entries. NULL is correct for
    # zero-rate/exempt categories; the form requires it when rate > 0.
    output_vat_account_id = db.Column(db.Integer, db.ForeignKey('accounts.id'),
                                      nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    created_at = db.Column(db.DateTime, default=ph_now)
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    updated_at = db.Column(db.DateTime, default=ph_now, onupdate=ph_now)
    updated_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))

    created_by = db.relationship('User', foreign_keys=[created_by_id],
                                 backref='sales_vat_categories_created')
    updated_by = db.relationship('User', foreign_keys=[updated_by_id],
                                 backref='sales_vat_categories_updated')
    output_vat_account = db.relationship('Account', foreign_keys=[output_vat_account_id])

    def __repr__(self):
        return f'<SalesVATCategory {self.code} - {self.name}>'

    def to_dict(self):
        return {
            'id': self.id,
            'code': self.code,
            'name': self.name,
            'description': self.description,
            'rate': float(self.rate) if self.rate else 0.0,
            'transaction_nature': self.transaction_nature,
            'output_vat_account_id': self.output_vat_account_id,
            'output_vat_account_code': self.output_vat_account.code if self.output_vat_account else None,
            'output_vat_account_name': self.output_vat_account.name if self.output_vat_account else None,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class SalesVATCategoryChangeRequest(db.Model):
    """Change request table for Sales VAT Category CRUD operations."""
    __tablename__ = 'sales_vat_category_change_requests'

    id = db.Column(db.Integer, primary_key=True)
    action = db.Column(db.String(20), nullable=False)   # 'create', 'update', 'delete'
    status = db.Column(db.String(20), default='pending', nullable=False)

    sales_vat_category_id = db.Column(db.Integer,
                                      db.ForeignKey('sales_vat_categories.id'),
                                      nullable=True)
    proposed_data = db.Column(db.Text)  # JSON string

    requested_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    requested_at = db.Column(db.DateTime, default=ph_now, nullable=False)
    reviewed_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    reviewed_at = db.Column(db.DateTime)
    review_notes = db.Column(db.Text)
    request_reason = db.Column(db.Text, nullable=True)

    sales_vat_category = db.relationship('SalesVATCategory', backref='change_requests')
    requested_by = db.relationship('User', foreign_keys=[requested_by_id],
                                   backref='sales_vat_category_requests')
    reviewed_by = db.relationship('User', foreign_keys=[reviewed_by_id],
                                  backref='sales_vat_category_reviews')

    def __repr__(self):
        return f'<SalesVATCategoryChangeRequest {self.action} - {self.status}>'

    def to_dict(self):
        return {
            'id': self.id,
            'action': self.action,
            'status': self.status,
            'sales_vat_category_id': self.sales_vat_category_id,
            'proposed_data': self.proposed_data,
            'requested_by': self.requested_by.full_name if self.requested_by else None,
            'requested_at': self.requested_at.isoformat() if self.requested_at else None,
            'reviewed_by': self.reviewed_by.full_name if self.reviewed_by else None,
            'reviewed_at': self.reviewed_at.isoformat() if self.reviewed_at else None,
            'review_notes': self.review_notes,
            'request_reason': self.request_reason,
        }
```

- [ ] **Step 4: Register the models for autodetect**

In `app/__init__.py`, directly after the existing line (≈175):
```python
from app.vat_categories.models import VATCategory, VATCategoryChangeRequest
```
add:
```python
from app.sales_vat_categories.models import SalesVATCategory, SalesVATCategoryChangeRequest
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/unit/test_sales_vat_category_model.py -v`
Expected: PASS (the `db_session` fixture creates all tables, so no migration needed for the test).

- [ ] **Step 6: Commit**

```bash
git add app/sales_vat_categories/__init__.py app/sales_vat_categories/models.py app/__init__.py tests/unit/test_sales_vat_category_model.py
git commit -m "feat(sales-vat): add SalesVATCategory + change-request models"
```

---

### Task 2: `WithholdingTax.sales_name` column

**Files:**
- Modify: `app/withholding_tax/models.py` (add column + to_dict key)
- Test: `tests/unit/test_withholding_tax_sales_name.py`

**Interfaces:**
- Produces: `WithholdingTax.sales_name` (String(100), nullable), surfaced in `.to_dict()` under key `sales_name`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_withholding_tax_sales_name.py
from decimal import Decimal
from app.withholding_tax.models import WithholdingTax


def test_sales_name_persists_and_in_to_dict(db_session):
    wt = WithholdingTax(code='WC010', name='Professional Fees - Individuals',
                        sales_name='Professional Fees Income - Individual',
                        rate=Decimal('10.00'), is_active=True)
    db_session.add(wt)
    db_session.commit()
    assert wt.sales_name == 'Professional Fees Income - Individual'
    assert wt.to_dict()['sales_name'] == 'Professional Fees Income - Individual'


def test_sales_name_is_optional(db_session):
    wt = WithholdingTax(code='WC999', name='Buyer only', rate=Decimal('1.00'))
    db_session.add(wt)
    db_session.commit()
    assert wt.sales_name is None
    assert wt.to_dict()['sales_name'] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_withholding_tax_sales_name.py -v`
Expected: FAIL — `TypeError: 'sales_name' is an invalid keyword argument for WithholdingTax`

- [ ] **Step 3: Add the column + to_dict key**

In `app/withholding_tax/models.py`, add directly after the `name` column:
```python
    # Seller/payee-POV name shown on sales documents (SI/CRV/customer). The
    # buyer-POV `name` stays for AP/CDV/vendor. Nullable + backfilled.
    sales_name = db.Column(db.String(100), nullable=True)
```
And add to its `to_dict()` (after the `name` key):
```python
            'sales_name': self.sales_name,
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_withholding_tax_sales_name.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/withholding_tax/models.py tests/unit/test_withholding_tax_sales_name.py
git commit -m "feat(wht): add seller-POV sales_name column"
```

---

### Task 3: Alembic migration — create sales tables + add `sales_name` (no drops yet)

**Files:**
- Create: `migrations/versions/<rev>_sales_vat_and_wht_sales_name.py` (via `flask db migrate`)
- Test: manual upgrade verification (no pytest; the test DB builds from models)

**Interfaces:**
- Produces: schema tables `sales_vat_categories`, `sales_vat_category_change_requests`, and column `withholding_tax.sales_name` in a real (non-test) DB.

- [ ] **Step 1: Autogenerate the migration**

Run: `flask db migrate -m "sales vat categories + wht sales_name"`
Expected: a new revision under `migrations/versions/`.

- [ ] **Step 2: Inspect the generated revision**

Open the new file. Confirm `upgrade()` contains `op.create_table('sales_vat_categories', ...)`, `op.create_table('sales_vat_category_change_requests', ...)`, and `op.add_column('withholding_tax', sa.Column('sales_name', sa.String(length=100), nullable=True))`. Confirm `downgrade()` drops them. **It must NOT drop `vat_categories.output_vat_account_id`** (that happens in Task 12). If autogen added that drop (it won't yet, since the model still has the column), remove it.

- [ ] **Step 3: Apply the migration**

Run: `flask db upgrade`
Expected: `Running upgrade ... -> <rev>` with no errors.

- [ ] **Step 4: Verify the schema**

Run: `python -c "from app import create_app, db; from sqlalchemy import inspect; app=create_app('development'); ctx=app.app_context(); ctx.push(); insp=inspect(db.engine); print('sales_vat_categories' in insp.get_table_names()); print([c['name'] for c in insp.get_columns('withholding_tax')])"`
Expected: prints `True` and a column list including `sales_name`.

- [ ] **Step 5: Commit**

```bash
git add migrations/versions/
git commit -m "migrate: create sales VAT tables + wht.sales_name"
```

---

### Task 4: Sales VAT cache helpers

**Files:**
- Modify: `app/utils/cache_helpers.py`
- Test: `tests/unit/test_sales_vat_cache.py`

**Interfaces:**
- Produces: `get_sales_vat_categories()` (active rows, ordered by code, memoized 1h) and `clear_sales_vat_cache()`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_sales_vat_cache.py
from decimal import Decimal
from app.utils.cache_helpers import get_sales_vat_categories, clear_sales_vat_cache
from app.sales_vat_categories.models import SalesVATCategory


def test_get_and_clear_sales_vat_cache(db_session):
    clear_sales_vat_cache()
    db_session.add(SalesVATCategory(code='SVAT-G', name='Goods', rate=Decimal('12.00'),
                                    transaction_nature='regular', is_active=True))
    db_session.commit()
    rows = get_sales_vat_categories()
    assert any(r.code == 'SVAT-G' for r in rows)
    clear_sales_vat_cache()  # must not raise
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_sales_vat_cache.py -v`
Expected: FAIL — `ImportError: cannot import name 'get_sales_vat_categories'`

- [ ] **Step 3: Add the helpers**

In `app/utils/cache_helpers.py`, add an import alongside the existing model imports:
```python
from app.sales_vat_categories.models import SalesVATCategory
```
Add after `get_vat_categories`:
```python
@cache.memoize(timeout=3600)
def get_sales_vat_categories():
    """Get all active Sales VAT categories (cached for 1 hour)."""
    return SalesVATCategory.query.filter_by(is_active=True).order_by(SalesVATCategory.code).all()
```
Add after `clear_vat_cache`:
```python
def clear_sales_vat_cache():
    """Clear Sales VAT category cache after updates."""
    cache.delete_memoized(get_sales_vat_categories)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_sales_vat_cache.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/utils/cache_helpers.py tests/unit/test_sales_vat_cache.py
git commit -m "feat(sales-vat): add cache helpers"
```

---

### Task 5: Sales VAT forms (admin-only, with `transaction_nature`)

**Files:**
- Create: `app/sales_vat_categories/forms.py`
- Test: `tests/unit/test_sales_vat_category_form.py`

**Interfaces:**
- Produces: `SalesVATCategoryForm` (fields: `code, name, description, rate, transaction_nature, output_vat_account_id, is_active, request_reason`; `output_vat_account_id` required when `rate > 0`), `SalesVATCategoryChangeReviewForm`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_sales_vat_category_form.py
from app.sales_vat_categories.forms import SalesVATCategoryForm


def test_output_account_required_when_rated(app):
    with app.test_request_context():
        form = SalesVATCategoryForm(meta={'csrf': False}, formdata=None)
        form.output_vat_account_id.choices = [(0, '--'), (5, '2100')]
        form.process(data={'code': 'SVAT-G', 'name': 'Goods', 'rate': '12.00',
                            'transaction_nature': 'regular', 'output_vat_account_id': 0,
                            'is_active': '1'})
        assert not form.validate()
        assert 'output_vat_account_id' in form.errors


def test_output_account_optional_when_zero(app):
    with app.test_request_context():
        form = SalesVATCategoryForm(meta={'csrf': False})
        form.output_vat_account_id.choices = [(0, '--'), (5, '2100')]
        form.process(data={'code': 'SVAT-EX', 'name': 'Exempt', 'rate': '0.00',
                            'transaction_nature': 'exempt', 'output_vat_account_id': 0,
                            'is_active': '1'})
        assert form.validate(), form.errors
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_sales_vat_category_form.py -v`
Expected: FAIL — `ModuleNotFoundError: app.sales_vat_categories.forms`

- [ ] **Step 3: Create the form**

Create `app/sales_vat_categories/forms.py` — mirror `app/vat_categories/forms.py`, dropping `input_vat_account_id`/`validate_input_vat_account_id`, keeping `output_vat_account_id`/`validate_output_vat_account_id`, and adding `transaction_nature`:

```python
"""Sales VAT Category forms."""
from flask_wtf import FlaskForm
from wtforms import StringField, TextAreaField, DecimalField, SelectField
from wtforms.validators import (DataRequired, InputRequired, Length, NumberRange,
                                Optional, ValidationError)

TRANSACTION_NATURE_CHOICES = [
    ('regular', 'Regular VATable'),
    ('zero_export', 'Zero-Rated (Export)'),
    ('zero_other', 'Zero-Rated (Other)'),
    ('exempt', 'VAT-Exempt'),
    ('government', 'Sales to Government'),
]


class SalesVATCategoryForm(FlaskForm):
    """Form for creating/editing Sales VAT categories."""
    code = StringField('Sales VAT Code', validators=[
        DataRequired(message='Sales VAT code is required'),
        Length(max=20, message='Code must be 20 characters or less')])
    name = StringField('Name', validators=[
        DataRequired(message='Name is required'),
        Length(max=100, message='Name must be 100 characters or less')])
    description = TextAreaField('Description', validators=[
        Optional(), Length(max=500, message='Description must be 500 characters or less')])
    rate = DecimalField('VAT Rate (%)', validators=[
        InputRequired(message='VAT rate is required'),
        NumberRange(min=0, max=100, message='VAT rate must be between 0 and 100')], places=2)
    transaction_nature = SelectField('Transaction Nature',
                                     choices=TRANSACTION_NATURE_CHOICES,
                                     validators=[DataRequired()], default='regular')
    output_vat_account_id = SelectField('Output Tax Account', coerce=int,
                                        validators=[], default=0)

    def validate_output_vat_account_id(self, field):
        rate = self.rate.data
        if rate is not None and rate > 0:
            if not field.data or field.data == 0:
                raise ValidationError(
                    'Output Tax account is required for VAT-bearing categories.')
        else:
            field.data = 0

    is_active = SelectField('Status', choices=[('1', 'Active'), ('0', 'Inactive')],
                            validators=[DataRequired()])
    request_reason = TextAreaField('Reason for Change', validators=[
        Optional(), Length(max=500, message='Reason must be 500 characters or less')],
        render_kw={'placeholder': 'Why is this change needed?', 'rows': 3})

    def __init__(self, *args, require_reason=False, **kwargs):
        super().__init__(*args, **kwargs)
        if require_reason:
            self.request_reason.validators = [
                DataRequired(message='Please explain why this change is needed'),
                Length(max=500, message='Reason must be 500 characters or less')]


class SalesVATCategoryChangeReviewForm(FlaskForm):
    """Form for reviewing change requests."""
    action = SelectField('Action', choices=[('approve', 'Approve'), ('reject', 'Reject')],
                         validators=[DataRequired()])
    review_notes = TextAreaField('Review Notes', validators=[
        Optional(), Length(max=500, message='Notes must be 500 characters or less')])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_sales_vat_category_form.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/sales_vat_categories/forms.py tests/unit/test_sales_vat_category_form.py
git commit -m "feat(sales-vat): add forms with transaction_nature"
```

---

### Task 6: `admin_required` gate + `can_auto_approve` (sole-admin) helper

**Files:**
- Create: `app/utils/admin_approval.py`
- Test: `tests/unit/test_admin_approval_helpers.py`

**Interfaces:**
- Produces: `admin_required(list_endpoint, noun)` decorator factory; `sole_admin_can_auto_approve()` → True iff `current_user.role == 'admin'` and exactly one active admin exists. These are shared by the sales-VAT, VAT, and WHT blueprints so the admin rule lives in one place.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_admin_approval_helpers.py
from app.utils.admin_approval import sole_admin_can_auto_approve
from app.users.models import User


def _login(client, username, password):  # fixtures use <username>123
    return client.post('/login', data={'username': username, 'password': password},
                       follow_redirects=True)


def test_sole_admin_auto_approves(app, db_session, admin_user):
    with app.test_request_context():
        from flask_login import login_user
        login_user(admin_user)
        assert sole_admin_can_auto_approve() is True


def test_two_admins_do_not_auto_approve(app, db_session, admin_user):
    second = User(username='admin2', email='a2@x.com', role='admin', is_active=True)
    second.set_password(second.username + '123')
    db_session.add(second)
    db_session.commit()
    with app.test_request_context():
        from flask_login import login_user
        login_user(admin_user)
        assert sole_admin_can_auto_approve() is False


def test_accountant_never_auto_approves(app, db_session, accountant_user):
    with app.test_request_context():
        from flask_login import login_user
        login_user(accountant_user)
        assert sole_admin_can_auto_approve() is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_admin_approval_helpers.py -v`
Expected: FAIL — `ModuleNotFoundError: app.utils.admin_approval`

- [ ] **Step 3: Create the helper module**

```python
# app/utils/admin_approval.py
"""Shared admin-only access + sole-admin auto-approval for tax maintenance
(VAT Categories, Sales VAT Categories, Withholding Tax). Replaces the older
accountant-centric rule for these three modules only (owner decision 2026-06-20).
"""
from functools import wraps
from flask import flash, redirect, url_for
from flask_login import current_user
from app.users.models import User


def admin_required(list_endpoint, noun):
    """Decorator factory: block non-admins (view + write) on tax maintenance."""
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            if not current_user.is_authenticated:
                return redirect(url_for('users.login'))
            if current_user.role != 'admin':
                flash(f'Only Administrators can access {noun}.', 'error')
                return redirect(url_for('dashboard.home'))
            return f(*args, **kwargs)
        return wrapped
    return decorator


def sole_admin_can_auto_approve():
    """True iff the actor is an admin AND exactly one active admin exists.
    A lone admin self-applies immediately; with >= 2 admins a different admin
    must approve (self-approval blocked at review time)."""
    if current_user.role != 'admin':
        return False
    total_admins = User.query.filter(User.role == 'admin', User.is_active == True).count()
    return total_admins == 1
```

> Note: confirm the dashboard endpoint name is `dashboard.home` (grep `def home` under `app/dashboard/`); adjust if different.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_admin_approval_helpers.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/utils/admin_approval.py tests/unit/test_admin_approval_helpers.py
git commit -m "feat(tax): shared admin-only gate + sole-admin auto-approve helper"
```

---

### Task 7: Sales VAT views + templates + blueprint registration

**Files:**
- Create: `app/sales_vat_categories/views.py`
- Create: `app/sales_vat_categories/templates/sales_vat_categories/{list,form,change_requests,review_change_request}.html`
- Modify: `app/__init__.py` (import + register blueprint)
- Test: `tests/integration/test_sales_vat_category_views.py`

**Interfaces:**
- Consumes: `SalesVATCategory`, `SalesVATCategoryChangeRequest` (Task 1); `SalesVATCategoryForm`, `SalesVATCategoryChangeReviewForm` (Task 5); `admin_required`, `sole_admin_can_auto_approve` (Task 6); `process_create_change_request` (`app/utils/change_requests.py`); `clear_sales_vat_cache` (Task 4).
- Produces: blueprint `sales_vat_categories_bp` at url_prefix `/sales-vat-categories`, endpoints `list_sales_vat_categories`, `create`, `edit`, `delete`, `change_requests`, `review_change_request`.

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_sales_vat_category_views.py
from app.sales_vat_categories.models import SalesVATCategory
from app.audit.models import AuditLog


def _login(client, user):
    return client.post('/login', data={'username': user.username, 'password': user.username + '123'},
                       follow_redirects=True)


class TestSalesVatAccess:
    def test_accountant_denied_list(self, client, db_session, accountant_user):
        _login(client, accountant_user)
        resp = client.get('/sales-vat-categories/', follow_redirects=False)
        assert resp.status_code == 302  # redirected to dashboard

    def test_admin_allowed_list(self, client, db_session, admin_user):
        _login(client, admin_user)
        resp = client.get('/sales-vat-categories/')
        assert resp.status_code == 200


class TestSalesVatCreate:
    def test_sole_admin_create_applies_and_audits(self, client, db_session, admin_user, db_with_data):
        # db_with_data provides accounts; pick an active leaf as output account
        from app.accounts.models import Account
        acct = Account.query.filter_by(is_active=True).first()
        _login(client, admin_user)
        resp = client.post('/sales-vat-categories/create', data={
            'code': 'SVAT-G', 'name': 'Sale of Goods (12%)', 'description': '',
            'rate': '12.00', 'transaction_nature': 'regular',
            'output_vat_account_id': str(acct.id), 'is_active': '1'},
            follow_redirects=True)
        assert resp.status_code == 200
        row = SalesVATCategory.query.filter_by(code='SVAT-G').first()
        assert row is not None  # sole admin auto-applied
        audit = AuditLog.query.filter_by(module='sales_vat_category', action='create').first()
        assert audit is not None
```

> Adjust the audit model import/path to match `app/audit/` (grep `class AuditLog`). The `db_with_data` fixture seeds accounts (see `tests/conftest.py`).

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/integration/test_sales_vat_category_views.py -v`
Expected: FAIL — 404 (blueprint not registered) / import error.

- [ ] **Step 3: Create the views by mirroring `app/vat_categories/views.py`**

Copy `app/vat_categories/views.py` → `app/sales_vat_categories/views.py` and apply this substitution map across the whole file:

| Replace | With |
|---|---|
| `VATCategory` | `SalesVATCategory` |
| `VATCategoryChangeRequest` | `SalesVATCategoryChangeRequest` |
| `VATCategoryForm` | `SalesVATCategoryForm` |
| `VATCategoryChangeReviewForm` | `SalesVATCategoryChangeReviewForm` |
| `vat_categories_bp` / `Blueprint('vat_categories'` | `sales_vat_categories_bp` / `Blueprint('sales_vat_categories'` |
| `vat_categories.list_vat_categories` | `sales_vat_categories.list_sales_vat_categories` |
| `vat_categories.change_requests` | `sales_vat_categories.change_requests` |
| `def list_vat_categories` | `def list_sales_vat_categories` |
| `vat_category_id` (CR FK + filters) | `sales_vat_category_id` |
| `module='vat_category'` | `module='sales_vat_category'` |
| `'vat_categories/...'` template paths | `'sales_vat_categories/...'` |
| `related_type='vat_category_request'` | `related_type='sales_vat_category_request'` |
| noun text "VAT category"/"VAT Category" | "Sales VAT category"/"Sales VAT Category" |

Then make these **behavioral** edits (not mechanical renames):

1. Imports: replace the local `accountant_or_admin_required` and `can_auto_approve` definitions with:
```python
from app.utils.admin_approval import admin_required, sole_admin_can_auto_approve
from app.utils.cache_helpers import clear_sales_vat_cache
```
   Delete the copied `accountant_or_admin_required` and `can_auto_approve` function bodies.
2. On every route decorator, replace `@accountant_or_admin_required` with `@admin_required('sales_vat_categories.list_sales_vat_categories', 'Sales VAT Categories')`. Apply it to `list_sales_vat_categories` too (admin-only view — there is no public list).
3. Replace every `can_auto_approve()` call with `sole_admin_can_auto_approve()`.
4. Remove all `input_vat_account_id` handling: drop `_input_vat_account_choices`, drop `form.input_vat_account_id.choices = ...`, and remove `input_vat_account_id` from every `change_data` dict, `model_to_dict([...])` field list, and the `change_requests` view's account batch-load (keep only output).
5. Add `transaction_nature` to every `change_data` dict (`'transaction_nature': form.transaction_nature.data`) and to the `model_to_dict([...])` field lists and the GET-prefill block (`form.transaction_nature.data = sales_vat_category.transaction_nature`).
6. After each successful auto-applied create/update/delete commit AND after each approval/rejection commit, call `clear_sales_vat_cache()`.
7. Update auto-approve audit notes from `'Auto-approved (single accountant)...'` to `'Auto-approved (single admin)...'` (the create path's note comes from `process_create_change_request`; see Task 8 — pass it through, or accept the shared default and fix in Task 8).

- [ ] **Step 4: Create the four templates**

Copy each `app/vat_categories/templates/vat_categories/<t>.html` → `app/sales_vat_categories/templates/sales_vat_categories/<t>.html`. In each: change `url_for('vat_categories.*')` → `url_for('sales_vat_categories.*')`; change visible "VAT" labels to "Sales VAT"; in `form.html` **remove the Input Tax Account field block** and **add a `transaction_nature` select** (render `form.transaction_nature` with its label, same markup pattern as the `is_active` select). Keep the delete modal HTML+CSRF (no JS popups). Keep design tokens.

- [ ] **Step 5: Register the blueprint**

In `app/__init__.py`, after the vat_categories blueprint import (≈196):
```python
from app.sales_vat_categories.views import sales_vat_categories_bp
```
After the vat_categories registration (≈217):
```python
app.register_blueprint(sales_vat_categories_bp, url_prefix='/sales-vat-categories')
```

- [ ] **Step 6: Run test to verify it passes**

Run: `pytest tests/integration/test_sales_vat_category_views.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add app/sales_vat_categories/ app/__init__.py tests/integration/test_sales_vat_category_views.py
git commit -m "feat(sales-vat): views, templates, blueprint (admin-only)"
```

---

### Task 8: Sole-admin audit note in `process_create_change_request`

**Files:**
- Modify: `app/utils/change_requests.py`
- Test: extend `tests/integration/test_sales_vat_category_views.py`

**Interfaces:**
- Consumes: existing `process_create_change_request(..., auto_approve, ...)`.
- Produces: an optional `approved_note` parameter (default keeps current `'Auto-approved (single accountant)'` for back-compat) so callers can pass `'Auto-approved (single admin)'`.

- [ ] **Step 1: Write the failing test** (add to the sales-vat view test file)

```python
    def test_create_audit_note_says_single_admin(self, client, db_session, admin_user, db_with_data):
        from app.accounts.models import Account
        from app.audit.models import AuditLog
        acct = Account.query.filter_by(is_active=True).first()
        _login(client, admin_user)
        client.post('/sales-vat-categories/create', data={
            'code': 'SVAT-S', 'name': 'Services', 'description': '', 'rate': '12.00',
            'transaction_nature': 'regular', 'output_vat_account_id': str(acct.id),
            'is_active': '1'}, follow_redirects=True)
        audit = AuditLog.query.filter_by(module='sales_vat_category', action='create').first()
        assert 'single admin' in (audit.notes or '')
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/integration/test_sales_vat_category_views.py -k single_admin -v`
Expected: FAIL — note says "single accountant".

- [ ] **Step 3: Add the parameter**

In `app/utils/change_requests.py`, change the signature to add `approved_note='Auto-approved (single accountant)'` and use it in the auto-approve branch's `log_audit(notes=approved_note)`. Then in `app/sales_vat_categories/views.py`'s `process_create_change_request(...)` call, pass `approved_note='Auto-approved (single admin)'`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/integration/test_sales_vat_category_views.py -k single_admin -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/utils/change_requests.py app/sales_vat_categories/views.py tests/integration/test_sales_vat_category_views.py
git commit -m "feat(sales-vat): single-admin audit note on auto-approved create"
```

---

### Task 9: Seed sales VAT rows + WT `sales_name` backfill (both paths)

**Files:**
- Modify: `app/fixtures.py`
- Modify: `app/seeds/seed_data.py`
- Test: `tests/integration/test_seed_sales_vat.py`

**Interfaces:**
- Produces: 5 `SalesVATCategory` rows (`SVAT-G/S/EX/ZR/GOV`) and `sales_name` set on WC010/WC011/WC100/WC158 after a seed.

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_seed_sales_vat.py
from app.fixtures import load_default_sales_vat_categories, load_default_withholding_tax
from app.sales_vat_categories.models import SalesVATCategory
from app.withholding_tax.models import WithholdingTax
from app.accounts.models import Account


def test_seed_sales_vat_categories(db_session):
    # output account 2100 must exist for rated rows
    db_session.add(Account(code='2100', name='Output Tax', account_type='Liability',
                           classification='Current', normal_balance='credit', is_active=True))
    db_session.commit()
    load_default_sales_vat_categories()
    codes = {c.code for c in SalesVATCategory.query.all()}
    assert {'SVAT-G', 'SVAT-S', 'SVAT-EX', 'SVAT-ZR', 'SVAT-GOV'} <= codes
    goods = SalesVATCategory.query.filter_by(code='SVAT-G').first()
    assert goods.transaction_nature == 'regular'
    assert goods.output_vat_account.code == '2100'
    exempt = SalesVATCategory.query.filter_by(code='SVAT-EX').first()
    assert exempt.output_vat_account_id is None


def test_seed_wht_sales_name_backfill(db_session):
    db_session.add(WithholdingTax(code='WC010', name='Professional Fees - Individuals',
                                  rate=10, is_active=True))
    db_session.commit()
    load_default_withholding_tax()  # idempotent; must backfill missing sales_name
    wt = WithholdingTax.query.filter_by(code='WC010').first()
    assert wt.sales_name == 'Professional Fees Income - Individual'
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/integration/test_seed_sales_vat.py -v`
Expected: FAIL — `ImportError: cannot import name 'load_default_sales_vat_categories'`

- [ ] **Step 3: Add the seed function + WT backfill (fixtures.py)**

In `app/fixtures.py`, add:
```python
def load_default_sales_vat_categories():
    """Seed default Sales (output) VAT categories. Idempotent."""
    from app.sales_vat_categories.models import SalesVATCategory
    if SalesVATCategory.query.count() > 0:
        print("  [SKIP] Sales VAT categories already exist")
        return SalesVATCategory.query.all()
    output_acct = Account.query.filter_by(code='2100').first()
    output_id = output_acct.id if output_acct else None
    rows = [
        SalesVATCategory(code='SVAT-G', name='Sale of Goods (12%)', rate=12.00,
                         transaction_nature='regular', output_vat_account_id=output_id, is_active=True),
        SalesVATCategory(code='SVAT-S', name='Sale of Services (12%)', rate=12.00,
                         transaction_nature='regular', output_vat_account_id=output_id, is_active=True),
        SalesVATCategory(code='SVAT-EX', name='VAT-Exempt Sales', rate=0.00,
                         transaction_nature='exempt', is_active=True),
        SalesVATCategory(code='SVAT-ZR', name='Zero-Rated Sales (Export)', rate=0.00,
                         transaction_nature='zero_export', is_active=True),
        SalesVATCategory(code='SVAT-GOV', name='Sales to Government (12%)', rate=12.00,
                         transaction_nature='government', output_vat_account_id=output_id, is_active=True),
    ]
    for r in rows:
        db.session.add(r)
    db.session.commit()
    print(f"  [OK] {len(rows)} default Sales VAT categories loaded")
    return rows
```
In the existing `load_default_withholding_tax`, add a `sales_name=` to each of the 4 `WithholdingTax(...)` constructors, and make it backfill on re-run. Replace the early `if WithholdingTax.query.count() > 0: return` guard so it still backfills `sales_name`:
```python
    SALES_NAMES = {
        'WC010': 'Professional Fees Income - Individual',
        'WC011': 'Professional Fees Income - Corporation',
        'WC100': 'Income as Contractor/Subcontractor',
        'WC158': 'Sale of Goods (subject to 1% CWT)',
    }
    existing = {w.code: w for w in WithholdingTax.query.all()}
    if existing:
        for code, sname in SALES_NAMES.items():
            if code in existing and not existing[code].sales_name:
                existing[code].sales_name = sname
        db.session.commit()
        print("  [OK] backfilled WT sales_name")
        return list(existing.values())
```
And add `sales_name=SALES_NAMES['WC010']` etc. to the 4 constructors in the create path. Finally, call `load_default_sales_vat_categories()` in the main seed orchestrator (right after `load_default_vat_categories()`, ≈line 333).

- [ ] **Step 4: Mirror into `app/seeds/seed_data.py`**

Apply the equivalent additions to `app/seeds/seed_data.py` (sales VAT rows + WT `sales_name`), matching whatever construction style that file uses. Grep it for `VATCategory(` and `WithholdingTax(` to find the insertion points.

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/integration/test_seed_sales_vat.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add app/fixtures.py app/seeds/seed_data.py tests/integration/test_seed_sales_vat.py
git commit -m "feat(sales-vat): seed sales categories + backfill WT sales_name (both paths)"
```

---

## Phase 2 — Rewire sales consumers to `SalesVATCategory`

### Task 10: SI + CRV read sales VAT (choices + output-account resolution)

**Files:**
- Modify: `app/sales_invoices/views.py` (`_vat_categories_for_form` ≈804; the `VATCategory.query.filter_by(code=...)` ≈833; `_output_vat_buckets` ≈192-209; the account-id set ≈1022-1024)
- Modify: `app/cash_receipts/views.py` (VAT list ≈548; the `VATCategory.query.filter_by(code=...)` ≈517; its output-bucket/posting equivalents)
- Test: `tests/integration/test_si_crv_use_sales_vat.py`

**Interfaces:**
- Consumes: `SalesVATCategory` (Task 1).
- Produces: SI/CRV VAT dropdowns + output-account posting resolved from `SalesVATCategory`. `VATCategory.output_vat_account` is no longer read by SI/CRV after this task.

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_si_crv_use_sales_vat.py
from app.sales_invoices.views import _vat_categories_for_form
from app.sales_vat_categories.models import SalesVATCategory
from app.vat_categories.models import VATCategory


def test_si_vat_choices_come_from_sales_table(db_session, app):
    db_session.add(SalesVATCategory(code='SVAT-G', name='Goods', rate=12.00,
                                    transaction_nature='regular', is_active=True))
    db_session.add(VATCategory(code='VAT-12', name='Purchase Goods', rate=12.00, is_active=True))
    db_session.commit()
    with app.test_request_context():
        codes = {c['code'] for c in _vat_categories_for_form()}
    assert 'SVAT-G' in codes
    assert 'VAT-12' not in codes  # purchase codes must NOT appear on SI
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/integration/test_si_crv_use_sales_vat.py -v`
Expected: FAIL — `VAT-12` present (still reading `VATCategory`).

- [ ] **Step 3: Repoint SI**

In `app/sales_invoices/views.py`: change the import to also import `SalesVATCategory`; in `_vat_categories_for_form` replace `VATCategory` with `SalesVATCategory`; replace the line-processing lookup `VATCategory.query.filter_by(code=vat_category, is_active=True).first()` with `SalesVATCategory.query.filter_by(code=vat_category, is_active=True).first()`; in `_output_vat_buckets` replace `VATCategory.query.all()` with `SalesVATCategory.query.all()` (the `.output_vat_account` attribute exists on the new model); replace the `{c.output_vat_account_id for c in VATCategory.query.all() ...}` set with `SalesVATCategory.query.all()`.

- [ ] **Step 4: Repoint CRV**

In `app/cash_receipts/views.py`: same substitutions — VAT list (≈548), the `filter_by(code=...)` lookup (≈517), and any output-account bucket/posting set → `SalesVATCategory`. Grep the file for `VATCategory` and switch every sales-posting reference (do NOT touch any AR/customer code unrelated to VAT).

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/integration/test_si_crv_use_sales_vat.py -v`
Expected: PASS
Also run the existing SI + CRV suites to catch regressions:
Run: `pytest tests/ -k "sales_invoice or cash_receipt" -q`
Expected: no NEW failures vs. baseline.

- [ ] **Step 6: Commit**

```bash
git add app/sales_invoices/views.py app/cash_receipts/views.py tests/integration/test_si_crv_use_sales_vat.py
git commit -m "refactor(si,crv): source VAT + output account from SalesVATCategory"
```

---

### Task 11: Customer `default_vat_category` reads sales VAT

**Files:**
- Modify: `app/customers/views.py` (`populate_dropdown_choices` ≈67-79)
- Test: `tests/integration/test_customer_default_vat_source.py`

**Interfaces:**
- Consumes: `SalesVATCategory`.
- Produces: customer `default_vat_category` choices sourced from `SalesVATCategory` (kept as `(name, name)` to preserve the existing customer storage convention).

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_customer_default_vat_source.py
from app.sales_vat_categories.models import SalesVATCategory
from app.vat_categories.models import VATCategory


def _login(client, user):
    return client.post('/login', data={'username': user.username, 'password': user.username + '123'},
                       follow_redirects=True)


def test_customer_form_lists_sales_vat_names(client, db_session, admin_user):
    db_session.add(SalesVATCategory(code='SVAT-G', name='Sale of Goods (12%)', rate=12.00,
                                    transaction_nature='regular', is_active=True))
    db_session.add(VATCategory(code='VAT-12', name='Purchase Goods (12%)', rate=12.00, is_active=True))
    db_session.commit()
    _login(client, admin_user)
    resp = client.get('/customers/create')
    assert b'Sale of Goods (12%)' in resp.data
    assert b'Purchase Goods (12%)' not in resp.data
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/integration/test_customer_default_vat_source.py -v`
Expected: FAIL — purchase name present.

- [ ] **Step 3: Repoint the customer populate function**

In `app/customers/views.py` `populate_dropdown_choices`: change the VAT block to query `SalesVATCategory` instead of `VATCategory` (import it), keeping `(cat.name, cat.name)` tuples and ordering by `name`. Leave the WT block for Task 13.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/integration/test_customer_default_vat_source.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/customers/views.py tests/integration/test_customer_default_vat_source.py
git commit -m "refactor(customers): default VAT category from SalesVATCategory"
```

---

## Phase 3 — Retire `VATCategory.output_vat_account_id`

### Task 12: Drop the output column (model + form + views + migration)

**Files:**
- Modify: `app/vat_categories/models.py` (remove `output_vat_account_id` column + relationship + to_dict keys)
- Modify: `app/vat_categories/forms.py` (remove `output_vat_account_id` field + `validate_output_vat_account_id`)
- Modify: `app/vat_categories/views.py` (remove `_output_vat_account_choices`, the `form.output_vat_account_id.*` lines, output keys in `change_data`/`model_to_dict`, output handling in `change_requests`/`review_change_request`)
- Create: `migrations/versions/<rev>_drop_vatcategory_output_account.py`
- Test: `tests/integration/test_vat_category_output_removed.py`

**Interfaces:**
- Produces: `VATCategory` with no `output_vat_account_id`; purchase create/edit works with input account only.

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_vat_category_output_removed.py
from app.vat_categories.models import VATCategory


def test_vatcategory_has_no_output_account_attr(db_session):
    cat = VATCategory(code='VAT-12', name='Goods', rate=12.00, is_active=True)
    db_session.add(cat)
    db_session.commit()
    assert not hasattr(cat, 'output_vat_account_id')
    assert 'output_vat_account_id' not in cat.to_dict()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/integration/test_vat_category_output_removed.py -v`
Expected: FAIL — attribute/key still present.

- [ ] **Step 3: Remove from model, form, views**

- `models.py`: delete the `output_vat_account_id` column (line 24), the `output_vat_account` relationship (line 36), and the three `output_vat_account*` keys in `to_dict` (lines 51-53).
- `forms.py`: delete `output_vat_account_id` field (40-41) and `validate_output_vat_account_id` (43-50).
- `views.py`: delete `_output_vat_account_choices` (67-68); delete `form.output_vat_account_id.choices = ...` in `create` and `edit`; remove `'output_vat_account_id'` from every `change_data` dict and every `model_to_dict([...])` list; remove `output_vat_account_id` from the `change_requests` batch-load and the `review_change_request` create/update apply blocks; delete the GET-prefill line `form.output_vat_account_id.data = ...`.

- [ ] **Step 4: Generate + edit the migration**

Run: `flask db migrate -m "drop vat_categories.output_vat_account_id"`
Open the revision. Ensure `upgrade()` first **copies data** then drops the column:
```python
def upgrade():
    conn = op.get_bind()
    # Copy any admin-set output accounts into the sales table (live DBs only;
    # seeded DBs have none). transaction_nature: rate>0 -> regular else zero_export.
    rows = conn.execute(sa.text(
        "SELECT code, name, rate, output_vat_account_id FROM vat_categories "
        "WHERE output_vat_account_id IS NOT NULL")).fetchall()
    for r in rows:
        exists = conn.execute(sa.text(
            "SELECT 1 FROM sales_vat_categories WHERE code = :c"), {"c": r.code}).fetchone()
        if exists:
            continue
        nature = 'regular' if (r.rate or 0) > 0 else 'zero_export'
        conn.execute(sa.text(
            "INSERT INTO sales_vat_categories (code, name, rate, transaction_nature, "
            "output_vat_account_id, is_active) VALUES (:c,:n,:r,:t,:o,1)"),
            {"c": r.code, "n": r.name, "r": r.rate, "t": nature, "o": r.output_vat_account_id})
    with op.batch_alter_table('vat_categories') as batch:
        batch.drop_column('output_vat_account_id')
```
(SQLite needs `batch_alter_table` to drop a column.) Give `downgrade()` an `add_column` to restore it nullable.

- [ ] **Step 5: Apply + run tests**

Run: `flask db upgrade`
Run: `pytest tests/integration/test_vat_category_output_removed.py -v`
Expected: PASS

- [ ] **Step 6: Run the VAT + purchase suites for regressions**

Run: `pytest tests/ -k "vat_categor or accounts_payable or cash_disburse" -q`
Expected: failures only in the known stale tests addressed in Task 17 (note them; don't fix here).

- [ ] **Step 7: Commit**

```bash
git add app/vat_categories/ migrations/versions/ tests/integration/test_vat_category_output_removed.py
git commit -m "refactor(vat): drop output_vat_account_id (now sales-only)"
```

---

## Phase 4 — Admin-lock existing tables, WT POV labels, nav, regression map, stale tests

### Task 13: Admin-lock `vat_categories` (gate + sole-admin approve)

**Files:**
- Modify: `app/vat_categories/views.py`
- Test: `tests/integration/test_vat_category_admin_only.py`

**Interfaces:**
- Consumes: `admin_required`, `sole_admin_can_auto_approve` (Task 6); `clear_vat_cache` (existing).
- Produces: `vat_categories` admin-only on every route incl. list; sole-admin auto-approve.

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_vat_category_admin_only.py
def _login(client, user):
    return client.post('/login', data={'username': user.username, 'password': user.username + '123'},
                       follow_redirects=True)


def test_accountant_denied_vat_list(client, db_session, accountant_user):
    _login(client, accountant_user)
    resp = client.get('/vat-categories/', follow_redirects=False)
    assert resp.status_code == 302


def test_admin_allowed_vat_list(client, db_session, admin_user):
    _login(client, admin_user)
    assert client.get('/vat-categories/').status_code == 200
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/integration/test_vat_category_admin_only.py -v`
Expected: FAIL — accountant gets 200 (list is currently `@login_required` only).

- [ ] **Step 3: Apply the admin gate + sole-admin approve**

In `app/vat_categories/views.py`: import `from app.utils.admin_approval import admin_required, sole_admin_can_auto_approve`; delete the local `accountant_or_admin_required` and `can_auto_approve`; decorate **every** route (incl. `list_vat_categories`) with `@admin_required('vat_categories.list_vat_categories', 'VAT Categories')`; replace `can_auto_approve()` calls with `sole_admin_can_auto_approve()`; update auto-approve audit-note text "single accountant" → "single admin"; ensure `clear_vat_cache()` is called after each mutation/approval (add if missing).

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/integration/test_vat_category_admin_only.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/vat_categories/views.py tests/integration/test_vat_category_admin_only.py
git commit -m "feat(vat): admin-only access + sole-admin auto-approve"
```

---

### Task 14: Admin-lock `withholding_tax` + `sales_name` in form/views

**Files:**
- Modify: `app/withholding_tax/forms.py` (add `sales_name` field)
- Modify: `app/withholding_tax/views.py` (admin gate, sole-admin approve, `sales_name` in change_data + apply paths + model_to_dict)
- Modify: `app/withholding_tax/templates/withholding_tax/form.html` (render `sales_name`)
- Test: `tests/integration/test_withholding_tax_admin_and_salesname.py`

**Interfaces:**
- Produces: WHT admin-only; create/edit persists `sales_name`.

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_withholding_tax_admin_and_salesname.py
from app.withholding_tax.models import WithholdingTax


def _login(client, user):
    return client.post('/login', data={'username': user.username, 'password': user.username + '123'},
                       follow_redirects=True)


def test_accountant_denied(client, db_session, accountant_user):
    _login(client, accountant_user)
    assert client.get('/withholding-tax/', follow_redirects=False).status_code == 302


def test_admin_create_persists_sales_name(client, db_session, admin_user):
    _login(client, admin_user)
    client.post('/withholding-tax/create', data={
        'code': 'WC010', 'name': 'Professional Fees - Individuals',
        'sales_name': 'Professional Fees Income - Individual', 'description': '',
        'rate': '10.00', 'is_active': '1'}, follow_redirects=True)
    wt = WithholdingTax.query.filter_by(code='WC010').first()
    assert wt is not None and wt.sales_name == 'Professional Fees Income - Individual'
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/integration/test_withholding_tax_admin_and_salesname.py -v`
Expected: FAIL — accountant 200 and/or `sales_name` not saved.

- [ ] **Step 3: Implement**

- `forms.py`: add after `name`:
```python
    sales_name = StringField('Sales Name (Seller POV)', validators=[
        Optional(), Length(max=100, message='Sales name must be 100 characters or less')])
```
  (import `Optional` is already present.)
- `views.py`: import + apply `admin_required('withholding_tax.list_withholding_tax', 'Withholding Tax')` on every route incl. list; swap `can_auto_approve` → `sole_admin_can_auto_approve`; add `'sales_name': form.sales_name.data` to every `change_data` dict; add `sales_name` to every `model_to_dict([...])` field list and to the create/update apply blocks in `review_change_request` (`sales_name=proposed_data.get('sales_name')`); add the GET-prefill `form.sales_name.data = withholding_tax.sales_name`; update audit note "single accountant" → "single admin".
- `form.html`: add a field block rendering `form.sales_name` (same markup as the `name` field), labeled so admins see it's the seller-POV name.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/integration/test_withholding_tax_admin_and_salesname.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/withholding_tax/ tests/integration/test_withholding_tax_admin_and_salesname.py
git commit -m "feat(wht): admin-only access + sales_name maintenance field"
```

---

### Task 15: POV-aware WT picker labels (SI/CRV/customer show `sales_name`)

**Files:**
- Modify: `app/sales_invoices/views.py` (`_wht_codes_for_form` ≈817) — emit a `sales_name`-based label
- Modify: `app/cash_receipts/views.py` (its WT codes builder)
- Modify: `app/customers/views.py` (WT block in `populate_dropdown_choices`)
- Modify: the SI/CRV form templates where the WT label is rendered (if the label text is built in the template from `to_dict()`), so sales forms show `sales_name`
- Test: `tests/integration/test_wt_pov_labels.py`

**Interfaces:**
- Consumes: `WithholdingTax.sales_name`, `.to_dict()` (now includes `sales_name`).
- Produces: a shared helper `wt_label(wt_dict, pov)` returning `sales_name`-or-`name` per POV; sales consumers use `pov='sales'`, purchase consumers `pov='buyer'` (default).

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_wt_pov_labels.py
from app.utils.wt_labels import wt_label


def test_sales_pov_prefers_sales_name():
    wt = {'code': 'WC010', 'name': 'Professional Fees - Individuals',
          'sales_name': 'Professional Fees Income - Individual', 'rate': 10.0}
    assert wt_label(wt, 'sales') == 'WC010 — Professional Fees Income - Individual'


def test_sales_pov_falls_back_to_name_when_empty():
    wt = {'code': 'WC999', 'name': 'Buyer only', 'sales_name': None, 'rate': 1.0}
    assert wt_label(wt, 'sales') == 'WC999 — Buyer only'


def test_buyer_pov_uses_name():
    wt = {'code': 'WC010', 'name': 'Professional Fees - Individuals',
          'sales_name': 'X', 'rate': 10.0}
    assert wt_label(wt, 'buyer') == 'WC010 — Professional Fees - Individuals'
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/integration/test_wt_pov_labels.py -v`
Expected: FAIL — `ModuleNotFoundError: app.utils.wt_labels`

- [ ] **Step 3: Create the helper + wire sales consumers**

```python
# app/utils/wt_labels.py
"""POV-aware Withholding Tax picker label. Sales documents show the seller-POV
sales_name (falling back to the buyer-POV name when blank); purchase documents
show name."""


def wt_label(wt_dict, pov='buyer'):
    code = wt_dict.get('code', '')
    if pov == 'sales':
        text = wt_dict.get('sales_name') or wt_dict.get('name', '')
    else:
        text = wt_dict.get('name', '')
    return f'{code} — {text}'
```
Then: in SI/CRV, where the WT `<option>` label is built, use `wt_label(w, 'sales')`. In `app/customers/views.py` WT block, build labels as `wt_label(wt.to_dict(), 'sales')` (or inline `wt.sales_name or wt.name`). Leave AP/CDV/vendor untouched (they default to buyer POV). If the SI/CRV label is constructed in JS from `to_dict()`, pass a `pov` flag or pre-format server-side; grep the SI/CRV form templates + form JS for where `wht`/`wt` option text is assembled.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/integration/test_wt_pov_labels.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/utils/wt_labels.py app/sales_invoices/views.py app/cash_receipts/views.py app/customers/views.py tests/integration/test_wt_pov_labels.py
git commit -m "feat(wht): POV-aware picker labels on sales documents"
```

---

### Task 16: Nav — gate VAT/Sales VAT/WHT to admin + add Sales VAT link

**Files:**
- Modify: `app/templates/base.html`
- Test: `tests/integration/test_nav_admin_gating.py`

**Interfaces:**
- Produces: VAT Categories, Sales VAT Categories, Withholding Tax nav links render only for `role == 'admin'`.

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_nav_admin_gating.py
def _login(client, user):
    return client.post('/login', data={'username': user.username, 'password': user.username + '123'},
                       follow_redirects=True)


def test_accountant_does_not_see_tax_nav(client, db_session, accountant_user):
    _login(client, accountant_user)
    resp = client.get('/')
    assert b'/vat-categories' not in resp.data
    assert b'/withholding-tax' not in resp.data
    assert b'/sales-vat-categories' not in resp.data


def test_admin_sees_tax_nav(client, db_session, admin_user):
    _login(client, admin_user)
    resp = client.get('/')
    assert b'/sales-vat-categories' in resp.data
```

> If `/` does not render the sidebar for these users, target the dashboard endpoint the app redirects to after login. Adjust the path in the test if needed.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/integration/test_nav_admin_gating.py -v`
Expected: FAIL — accountant still sees the links (current gate is `['admin','accountant']`); no Sales VAT link.

- [ ] **Step 3: Edit base.html**

Find the VAT/WHT nav block (≈1193-1201). Per grep-siblings, **grep base.html for every `vat_categories.`, `withholding_tax.`, and the text "Withholding Tax"** — there may be a second WHT nav entry ("…Final"). Change the wrapping gate from `current_user.role in ['admin', 'accountant']` to `current_user.role == 'admin'` for all of them. Add a Sales VAT link inside the admin-gated block:
```html
<a href="{{ url_for('sales_vat_categories.list_sales_vat_categories') }}" class="nav-item {% if request.endpoint and request.endpoint.startswith('sales_vat_categories.') %}active{% endif %}">
    <span class="nav-icon">🧾</span>
    <span class="nav-text">Sales VAT Categories</span>
</a>
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/integration/test_nav_admin_gating.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/templates/base.html tests/integration/test_nav_admin_gating.py
git commit -m "feat(nav): admin-only tax maintenance + Sales VAT link"
```

---

### Task 17: Regression map + stale-test sweep + full suite

**Files:**
- Modify: `.claude/regression-map.json`
- Modify: stale tests surfaced by the full run (test-only)
- Test: the whole suite

**Interfaces:**
- Produces: `regression-map.json` aware of `sales_vat_categories`; green suite modulo the documented baseline.

- [ ] **Step 1: Add the regression-map entries**

In `.claude/regression-map.json`: add blast-radius keys
```json
"app/sales_vat_categories/models.py": ["sales_invoices", "cash_receipts", "customers"],
"app/sales_vat_categories/views.py":  ["sales_vat_categories"],
"app/utils/admin_approval.py":        ["vat_categories", "withholding_tax", "sales_vat_categories"],
"app/utils/wt_labels.py":             ["sales_invoices", "cash_receipts", "customers"],
```
and a module entry `"sales_vat_categories": { "marker": "sales_vat", "e2e": null }` (match the file's existing module-block shape).

- [ ] **Step 2: Run the full suite**

Run: `pytest -q`
Expected: failures limited to (a) the documented baseline failures and (b) stale VAT/WHT tests that log in as accountant or assert `output_vat_account_id`/the old "single accountant" note.

- [ ] **Step 3: Fix stale tests (test-only)**

For each stale failure: switch the actor from `accountant_user` to `admin_user`; drop `output_vat_account_id` from VAT form POST payloads and assertions; change expected audit note "single accountant" → "single admin" for VAT/WHT; update `test_vat_create_form_toggle_driven_by_select_value` and any "accountant can edit VAT/WHT" expectations to the admin-only reality. Per the spec, also reconcile the deferred `test_customer_vat_label_unchanged` guard (now pinning "Registration Type"). Do NOT alter product code to satisfy a stale test — confirm each is genuinely stale (the behavior change is intended) before editing it.

- [ ] **Step 4: Re-run + confirm green-vs-baseline**

Run: `pytest -q`
Expected: only the known baseline failures remain.

- [ ] **Step 5: Commit**

```bash
git add .claude/regression-map.json tests/
git commit -m "test+guard: regression map for sales VAT + stale-test sweep"
```

---

## Self-Review (completed by plan author)

**Spec coverage:** §1 model → Tasks 1,2,3,12; §1c data-migration + drop → Task 12; §2 admin access → Tasks 6,13,14,16; §2 approval → Tasks 6,8,13,14; §3 consumer rewiring → Tasks 10,11,15; §3 cache/populate → Tasks 4,10,11; §4 seed → Task 9; §5 tests/regression/nav → Tasks 7,13–17. All spec sections map to a task.

**Placeholder scan:** No TBD/TODO; the few "grep to confirm" notes (dashboard endpoint name, second WHT nav twin, SI/CRV WT label site, audit model path) are explicit verification steps, not deferred work — each names exactly what to check and what to do.

**Type/name consistency:** `SalesVATCategory`/`SalesVATCategoryChangeRequest`, `sales_vat_categories_bp`, `list_sales_vat_categories`, `transaction_nature` enum, `sales_name`, `get_sales_vat_categories`/`clear_sales_vat_cache`, `admin_required(list_endpoint, noun)`, `sole_admin_can_auto_approve()`, `wt_label(wt_dict, pov)` — used consistently across tasks.

**Ordering safety:** sales table + consumers (Phase 1–2) precede the `output_vat_account_id` drop (Phase 3); admin-lock (Phase 4) is independent and last. App builds and serves at every commit.
