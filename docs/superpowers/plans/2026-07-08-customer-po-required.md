# Customer PO Required Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a customer be flagged "Purchase Order required" so that confirming a Sales Order for that customer is blocked when the SO's Customer PO # is blank.

**Architecture:** A nullable-false `po_required` boolean on `Customer` (one batch migration) surfaced as a checkbox on the customer form; a guard in `sales_orders.confirm` that reads `so.customer.po_required` (existing relationship) and refuses draft→confirmed when the PO number is empty.

**Tech Stack:** Flask + SQLAlchemy + SQLite; Flask-Migrate/Alembic (hand-written batch, `render_as_batch` OFF); pytest (`-p no:cov`).

## Global Constraints

- **`po_required` defaults to `False`** — every existing customer is unaffected.
- **Enforcement is at Confirm only** — creating/editing/saving a draft never checks the PO.
- **PO number only** — the PO date stays optional.
- Migrations are hand-written batch, verified on a **copy of `cas.db`**. `down_revision = 'b7780a041539'`.

---

### Task 1: `po_required` column on Customer + migration

**Files:**
- Modify: `app/customers/models.py::Customer` (add column near `is_active` ~line 41; add `to_dict` key ~line 79)
- Create: `migrations/versions/<generated>_add_po_required_to_customers.py`
- Test: `tests/unit/test_customer_po_required.py`

**Interfaces:**
- Produces: `Customer.po_required` (bool, default False); `Customer.to_dict()` gains `'po_required'`.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_customer_po_required.py`:

```python
import pytest
from app import db
from app.customers.models import Customer

pytestmark = [pytest.mark.integration, pytest.mark.customers]


def test_customer_po_required_defaults_false_and_in_to_dict(db_session):
    c = Customer(code='C-PO1', name='NoPO Corp', is_active=True)
    db.session.add(c); db.session.commit()
    assert c.po_required is False
    assert c.to_dict()['po_required'] is False
    c2 = Customer(code='C-PO2', name='PO Corp', is_active=True, po_required=True)
    db.session.add(c2); db.session.commit()
    assert c2.to_dict()['po_required'] is True
```

- [ ] **Step 2: Run to verify it fails**

Run: `venv/Scripts/python.exe -m pytest tests/unit/test_customer_po_required.py -p no:cov -v`
Expected: FAIL — `Customer` has no `po_required` attribute.

- [ ] **Step 3: Add the column + to_dict key**

In `app/customers/models.py`, right after `is_active = db.Column(...)`:

```python
    po_required = db.Column(db.Boolean, default=False, nullable=False)
```

In `Customer.to_dict()`, after the `'is_active': self.is_active,` line, add:

```python
            'po_required': self.po_required,
```

- [ ] **Step 4: Run to verify it passes**

Run: `venv/Scripts/python.exe -m pytest tests/unit/test_customer_po_required.py -p no:cov -v`
Expected: PASS (the conftest builds tables from the model, so the column exists in-test).

- [ ] **Step 5: Scaffold + write the batch migration**

Run: `venv/Scripts/python.exe -m flask db revision -m "add po_required to customers"`

Replace the body (`down_revision` is already `b7780a041539`):

```python
def upgrade():
    with op.batch_alter_table('customers', schema=None) as batch_op:
        batch_op.add_column(sa.Column('po_required', sa.Boolean(), nullable=False,
                                      server_default=sa.false()))
    with op.batch_alter_table('customers', schema=None) as batch_op:
        batch_op.alter_column('po_required', server_default=None)


def downgrade():
    with op.batch_alter_table('customers', schema=None) as batch_op:
        batch_op.drop_column('po_required')
```

- [ ] **Step 6: Verify on a copy of cas.db, then apply**

```bash
cp instance/cas.db instance/_x.db
SQLALCHEMY_DATABASE_URI=sqlite:///_x.db venv/Scripts/python.exe -m flask db upgrade
venv/Scripts/python.exe -c "import sqlite3; c=sqlite3.connect('instance/_x.db'); \
print('po_required' in [r[1] for r in c.execute('PRAGMA table_info(customers)')])"
rm -f instance/_x.db
venv/Scripts/python.exe -m flask db upgrade
```

Expected: prints `True`; the demo DB upgrade runs cleanly.

- [ ] **Step 7: Commit**

```bash
git add app/customers/models.py migrations/versions/*add_po_required_to_customers*.py \
        tests/unit/test_customer_po_required.py
git commit -m "feat(customers): add po_required flag (nullable-false, default False)"
```

---

### Task 2: Customer form checkbox + persist

**Files:**
- Modify: `app/customers/forms.py::CustomerForm` (add field + `BooleanField` import), `app/customers/views.py` (create constructor ~line 268; edit assignment ~line 361), `app/customers/templates/customers/_form_fields.html` (~line 25, after the status toggle)
- Test: `tests/integration/test_customers.py`

**Interfaces:**
- Consumes: `Customer.po_required` (Task 1).
- Produces: create/edit persist `po_required` from the form checkbox.

- [ ] **Step 1: Write the failing test**

Add to `tests/integration/test_customers.py` (reuse its login/branch fixtures; check how a nearby create test posts the form and mirror its required fields — `code`, `name`, `payment_terms`, `is_active`):

```python
def test_customer_create_persists_po_required(client, db_session, admin_user, main_branch, login_user):
    from app.customers.models import Customer
    login_user(client, 'admin', 'admin123')
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = main_branch.id
    client.post('/customers/create', data={
        'code': 'C-POREQ', 'name': 'PO Required Corp', 'payment_terms': 'Net 30',
        'is_active': '1', 'po_required': 'y'}, follow_redirects=True)
    c = Customer.query.filter_by(code='C-POREQ').first()
    assert c is not None and c.po_required is True
```

(WTForms `BooleanField` treats any present non-empty value — e.g. `'y'` — as checked; omit the key for unchecked.)

- [ ] **Step 2: Run to verify it fails**

Run: `venv/Scripts/python.exe -m pytest "tests/integration/test_customers.py::test_customer_create_persists_po_required" -p no:cov -v`
Expected: FAIL — the view ignores `po_required` (stays False), OR the form has no such field.

- [ ] **Step 3: Add the form field**

In `app/customers/forms.py`, add `BooleanField` to the `wtforms` import and add the field to `CustomerForm`:

```python
from wtforms import StringField, TextAreaField, SelectField, BooleanField
```
```python
    po_required = BooleanField('Requires Purchase Order')
```

- [ ] **Step 4: Persist in create + edit**

In `app/customers/views.py`, in the `Customer(...)` constructor (after the `is_active=...` line ~268):

```python
                po_required=bool(form.po_required.data),
```

In the edit update block (after `customer.is_active = bool(int(form.is_active.data))` ~line 361):

```python
            customer.po_required = bool(form.po_required.data)
```

(Edit's `form = CustomerForm(obj=customer)` auto-populates the checkbox from `customer.po_required`, so no GET pre-fill is needed.)

- [ ] **Step 5: Render the checkbox on the form**

In `app/customers/templates/customers/_form_fields.html`, immediately after `{{ status_toggle(form.is_active, label_class='') }}`:

```html
        <div class="form-group">
            <label style="display:flex; align-items:center; gap:8px; cursor:pointer;">
                {{ form.po_required(style="width:auto; margin:0;") }}
                {{ form.po_required.label.text }}
            </label>
            <small class="form-hint">When set, a Purchase Order number is required before a Sales Order for this customer can be confirmed.</small>
        </div>
```

- [ ] **Step 6: Run the test + customer suite**

Run: `venv/Scripts/python.exe -m pytest "tests/integration/test_customers.py::test_customer_create_persists_po_required" -p no:cov -v`
then `venv/Scripts/python.exe -m pytest tests/integration/test_customers.py -p no:cov -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add app/customers/forms.py app/customers/views.py \
        app/customers/templates/customers/_form_fields.html tests/integration/test_customers.py
git commit -m "feat(customers): 'Requires Purchase Order' checkbox (form + create/edit persist)"
```

---

### Task 3: Block SO confirm when a PO-required customer has no PO

**Files:**
- Modify: `app/sales_orders/views.py::confirm()` (after the `status == 'draft'` check, before the status flip)
- Test: `tests/integration/test_so_status.py`

**Interfaces:**
- Consumes: `Customer.po_required` (Task 1); `SalesOrder.customer` (existing relationship), `SalesOrder.customer_po_number`.

- [ ] **Step 1: Write the failing test**

Add to `tests/integration/test_so_status.py` (reuse its `customer` / `_login` / `_select_branch` helpers and the autouse `sales_orders_module_enabled` fixture). Build a PO-required customer + a draft SO with a blank PO, POST confirm, assert it stays draft:

```python
def test_confirm_blocked_when_po_required_and_blank(client, db_session, admin_user, main_branch):
    from app.customers.models import Customer
    from app.sales_orders.models import SalesOrder
    import datetime
    cust = Customer(code='C-POREQ', name='PO Corp', is_active=True, po_required=True)
    db_session.add(cust); db_session.commit()
    _login(client, admin_user); _select_branch(client, main_branch.id)
    so = SalesOrder(so_number='SO-PO-1', order_date=datetime.date(2026, 7, 8),
                    customer_id=cust.id, customer_name='PO Corp', branch_id=main_branch.id,
                    status='draft', customer_po_number=None)
    db_session.add(so); db_session.commit()
    client.post(f'/sales-orders/{so.id}/confirm', follow_redirects=True)
    db_session.refresh(so)
    assert so.status == 'draft' and so.confirmed_at is None


def test_confirm_ok_when_po_required_and_filled(client, db_session, admin_user, main_branch):
    from app.customers.models import Customer
    from app.sales_orders.models import SalesOrder
    import datetime
    cust = Customer(code='C-POREQ2', name='PO Corp 2', is_active=True, po_required=True)
    db_session.add(cust); db_session.commit()
    _login(client, admin_user); _select_branch(client, main_branch.id)
    so = SalesOrder(so_number='SO-PO-2', order_date=datetime.date(2026, 7, 8),
                    customer_id=cust.id, customer_name='PO Corp 2', branch_id=main_branch.id,
                    status='draft', customer_po_number='PO-12345')
    db_session.add(so); db_session.commit()
    client.post(f'/sales-orders/{so.id}/confirm', follow_redirects=True)
    db_session.refresh(so)
    assert so.status == 'confirmed'
```

- [ ] **Step 2: Run to verify it fails**

Run: `venv/Scripts/python.exe -m pytest "tests/integration/test_so_status.py::test_confirm_blocked_when_po_required_and_blank" -p no:cov -v`
Expected: FAIL — no guard, so the SO confirms (status becomes `confirmed`).

- [ ] **Step 3: Add the guard**

In `app/sales_orders/views.py`, inside `confirm()`, after the `if so.status != 'draft':` block and **before** `so.status = 'confirmed'`:

```python
    if so.customer and so.customer.po_required and not (so.customer_po_number or '').strip():
        flash(f'Customer "{so.customer_name}" requires a Purchase Order number before this '
              f'Sales Order can be confirmed.', 'error')
        return redirect(url_for('sales_orders.view', id=id))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `venv/Scripts/python.exe -m pytest "tests/integration/test_so_status.py::test_confirm_blocked_when_po_required_and_blank" "tests/integration/test_so_status.py::test_confirm_ok_when_po_required_and_filled" -p no:cov -v`
Expected: PASS.

- [ ] **Step 5: Run the SO marker suite (no regression)**

Run: `venv/Scripts/python.exe -m pytest -m sales_orders -p no:cov -q`
Expected: PASS (non-flagged-customer confirm tests still pass — the guard is a no-op when `po_required` is False).

- [ ] **Step 6: Commit**

```bash
git add app/sales_orders/views.py tests/integration/test_so_status.py
git commit -m "feat(sales-orders): block confirm when a PO-required customer has no PO number"
```

---

## Post-implementation

- Browser-verify: on a customer, tick "Requires Purchase Order" + save; create a draft SO for that
  customer with a blank Customer PO #, click Confirm → blocked with the flash; fill the PO # → confirms.
- A non-flagged customer confirms with a blank PO exactly as before.
- `/guard cas` before pushing (Customer model + SO confirm are blast-radius).
