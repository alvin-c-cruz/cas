# Salesperson Attribution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Record a salesperson (an `Employee`) on the Sales Order and Sales Invoice, gated on the Employees module, and show the name on the SI printouts — the field + manual entry now; the SO→DR→SI auto-fill cascade deferred to the unbuilt chain.

**Architecture:** A nullable `salesperson_id` FK → `employees` on both headers (one batch migration); an Employee `<select>` on the SO/SI forms rendered only when `module_enabled('employees')`; the SI `print.html`/`detail.html`/`print_preprinted.html` render the employee `full_name`; a `copy_salesperson(src, dst)` helper stubbed for the future cascade.

**Tech Stack:** Flask + SQLAlchemy + SQLite; Flask-Migrate/Alembic (hand-written batch, `render_as_batch` OFF); pytest (`-p no:cov`).

## Global Constraints

- **`salesperson_id` is nullable** — not every document has a rep; keeps existing rows valid.
- **Salesperson = `Employee`** — FK to `employees`; the picker + list are **branch-scoped** and **active-only**.
- **Gated on the Employees module** (`module_enabled('employees')`, optional/default-off): no picker, no requirement when off.
- **No FK-enforcement worry** (SQLite FKs off app-wide); migrations are hand-written batch, verified on a **copy of `cas.db`**.
- **Auto-fill cascade is NOT wired** in v1 (no chain yet) — only the `copy_salesperson` helper exists.
- Migration `down_revision` is the current head **`0561206ba8e1`**.

---

### Task 1: Models + migration + `copy_salesperson`

**Files:**
- Modify: `app/sales_orders/models.py::SalesOrder`, `app/sales_invoices/models.py::SalesInvoice`
- Create: `app/sales_orders/../utils`-level helper — put `copy_salesperson` in `app/sales_orders/models.py` module scope (imported where needed)
- Create: `migrations/versions/<generated>_add_salesperson_id.py`
- Test: `tests/unit/test_salesperson_field.py`

**Interfaces:**
- Produces: `SalesOrder.salesperson_id` / `SalesInvoice.salesperson_id` (int|None), `.salesperson` (Employee|None); `to_dict()` gains `salesperson_id` + `salesperson_name`; `copy_salesperson(src, dst)` sets `dst.salesperson_id = src.salesperson_id`.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_salesperson_field.py`:

```python
import pytest
from datetime import date
from app import db
from app.employees.models import Employee
from app.sales_orders.models import SalesOrder, copy_salesperson

pytestmark = [pytest.mark.integration, pytest.mark.sales_orders]


def _emp(db_session, branch_id):
    e = Employee(employee_no='E-001', first_name='Jane', last_name='Cruz',
                 branch_id=branch_id, is_active=True)
    db_session.add(e); db_session.commit()
    return e


def test_so_salesperson_fk_and_to_dict(db_session, main_branch):
    e = _emp(db_session, main_branch.id)
    so = SalesOrder(so_number='SO-SP-1', order_date=date(2026, 7, 8), customer_id=1,
                    customer_name='Acme', branch_id=main_branch.id, salesperson_id=e.id)
    db_session.add(so); db_session.commit()
    assert so.salesperson.full_name == 'Jane Cruz'
    d = so.to_dict()
    assert d['salesperson_id'] == e.id and d['salesperson_name'] == 'Jane Cruz'
    # null case
    so2 = SalesOrder(so_number='SO-SP-2', order_date=date(2026, 7, 8), customer_id=1,
                     customer_name='Acme', branch_id=main_branch.id)
    db_session.add(so2); db_session.commit()
    assert so2.to_dict()['salesperson_name'] is None


def test_copy_salesperson(db_session, main_branch):
    e = _emp(db_session, main_branch.id)
    src = SalesOrder(so_number='SO-SP-3', order_date=date(2026, 7, 8), customer_id=1,
                     customer_name='Acme', branch_id=main_branch.id, salesperson_id=e.id)
    dst = SalesOrder(so_number='SO-SP-4', order_date=date(2026, 7, 8), customer_id=1,
                     customer_name='Acme', branch_id=main_branch.id)
    copy_salesperson(src, dst)
    assert dst.salesperson_id == e.id
```

- [ ] **Step 2: Run to verify it fails**

Run: `venv/Scripts/python.exe -m pytest tests/unit/test_salesperson_field.py -p no:cov -v`
Expected: FAIL — `ImportError` on `copy_salesperson` / `SalesOrder` has no `salesperson_id`.

- [ ] **Step 3: Add the field + relationship + to_dict + helper to `SalesOrder`**

In `app/sales_orders/models.py`, in `SalesOrder` (near `created_by_id`), add:

```python
    salesperson_id = db.Column(db.Integer, db.ForeignKey('employees.id'), nullable=True, index=True)
    salesperson = db.relationship('Employee', foreign_keys=[salesperson_id])
```

Add to `SalesOrder.to_dict()`:

```python
            'salesperson_id': self.salesperson_id,
            'salesperson_name': self.salesperson.full_name if self.salesperson else None,
```

At module scope (bottom of `app/sales_orders/models.py`), add:

```python
def copy_salesperson(src, dst):
    """Carry the salesperson down the SO->DR->SI chain (future cascade hook)."""
    dst.salesperson_id = src.salesperson_id
```

- [ ] **Step 4: Add the same field + relationship + to_dict to `SalesInvoice`**

In `app/sales_invoices/models.py`, in `SalesInvoice` (near `created_by_id`), add the identical two lines:

```python
    salesperson_id = db.Column(db.Integer, db.ForeignKey('employees.id'), nullable=True, index=True)
    salesperson = db.relationship('Employee', foreign_keys=[salesperson_id])
```

Add to `SalesInvoice.to_dict()`:

```python
            'salesperson_id': self.salesperson_id,
            'salesperson_name': self.salesperson.full_name if self.salesperson else None,
```

- [ ] **Step 5: Run the model test to verify it passes**

Run: `venv/Scripts/python.exe -m pytest tests/unit/test_salesperson_field.py -p no:cov -v`
Expected: PASS (the conftest `db_session` builds tables from the models, so the columns exist in-test).

- [ ] **Step 6: Scaffold + write the batch migration**

Run: `venv/Scripts/python.exe -m flask db revision -m "add salesperson_id to sales_orders and sales_invoices"`

Replace the body with (`down_revision` will already be `0561206ba8e1`):

```python
def upgrade():
    with op.batch_alter_table('sales_orders', schema=None) as batch_op:
        batch_op.add_column(sa.Column('salesperson_id', sa.Integer(), nullable=True))
        batch_op.create_index(batch_op.f('ix_sales_orders_salesperson_id'), ['salesperson_id'])
    with op.batch_alter_table('sales_invoices', schema=None) as batch_op:
        batch_op.add_column(sa.Column('salesperson_id', sa.Integer(), nullable=True))
        batch_op.create_index(batch_op.f('ix_sales_invoices_salesperson_id'), ['salesperson_id'])


def downgrade():
    with op.batch_alter_table('sales_invoices', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_sales_invoices_salesperson_id'))
        batch_op.drop_column('salesperson_id')
    with op.batch_alter_table('sales_orders', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_sales_orders_salesperson_id'))
        batch_op.drop_column('salesperson_id')
```

- [ ] **Step 7: Verify on a copy of `cas.db`, then apply**

```bash
cp instance/cas.db instance/_x.db
SQLALCHEMY_DATABASE_URI=sqlite:///_x.db venv/Scripts/python.exe -m flask db upgrade
venv/Scripts/python.exe -c "import sqlite3; c=sqlite3.connect('instance/_x.db'); \
print('so:', 'salesperson_id' in [r[1] for r in c.execute('PRAGMA table_info(sales_orders)')], \
'si:', 'salesperson_id' in [r[1] for r in c.execute('PRAGMA table_info(sales_invoices)')])"
rm -f instance/_x.db
venv/Scripts/python.exe -m flask db upgrade   # apply to the demo DB
```

Expected: prints `so: True si: True`; then the demo DB upgrade runs cleanly.

- [ ] **Step 8: Commit**

```bash
git add app/sales_orders/models.py app/sales_invoices/models.py \
        migrations/versions/*add_salesperson_id*.py tests/unit/test_salesperson_field.py
git commit -m "feat(sales): salesperson_id FK (Employee) on SO + SI + copy_salesperson helper"
```

---

### Task 2: Sales Order — salesperson picker (form + view + template)

**Files:**
- Modify: `app/sales_orders/forms.py::SalesOrderForm`, `app/sales_orders/views.py` (create + edit), `app/sales_orders/templates/sales_orders/form.html`
- Test: `tests/integration/test_sales_orders_crud.py`

**Interfaces:**
- Consumes: `SalesOrder.salesperson_id` (Task 1).
- Produces: SO create/edit persists `salesperson_id`; the picker renders only when `module_enabled('employees')`.

- [ ] **Step 1: Write the failing test**

Add to `tests/integration/test_sales_orders_crud.py`:

```python
def test_so_persists_salesperson_when_employees_enabled(client, db_session, admin_user, main_branch):
    from app.employees.models import Employee
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    AppSettings.set_setting('module_enabled:employees', '1')
    db_session.commit(); clear_module_config_cache()
    e = Employee(employee_no='E-9', first_name='Rey', last_name='Santos',
                 branch_id=main_branch.id, is_active=True)
    db_session.add(e); db_session.commit()
    c = _customer(db_session); p = _product(db_session)
    _login(client, admin_user); _select_branch(client, main_branch.id)
    lines = json.dumps([{'product_id': str(p.id), 'quantity': '1', 'unit_price': '100.00',
                         'vat_category': None, 'vat_rate': '0'}])
    client.post('/sales-orders/create', data={
        'so_number': 'SO-SP-100', 'order_date': '2026-07-08', 'customer_id': str(c.id),
        'customer_name': 'Acme', 'payment_terms': 'Net 30', 'notes': '',
        'salesperson_id': str(e.id), 'line_items': lines}, follow_redirects=True)
    so = SalesOrder.query.filter_by(so_number='SO-SP-100').first()
    assert so is not None and so.salesperson_id == e.id
```

- [ ] **Step 2: Run to verify it fails**

Run: `venv/Scripts/python.exe -m pytest "tests/integration/test_sales_orders_crud.py::test_so_persists_salesperson_when_employees_enabled" -p no:cov -v`
Expected: FAIL — `salesperson_id` is not read by the view, so `so.salesperson_id` is None.

- [ ] **Step 3: Add the form field**

In `app/sales_orders/forms.py`, add to `SalesOrderForm` (import `SelectField` + `Optional` if missing):

```python
    salesperson_id = SelectField('Salesperson', coerce=int, validators=[Optional()],
                                 validate_choice=False)
```

- [ ] **Step 4: Populate choices + persist in the view**

In `app/sales_orders/views.py`, add a helper near `_common_form_ctx`:

```python
def _salesperson_choices(branch_id):
    from app.users.module_access import module_enabled
    from app.employees.models import Employee
    choices = [(0, '-- None --')]
    if module_enabled('employees') and branch_id:
        emps = (Employee.query.filter_by(is_active=True, branch_id=branch_id)
                .order_by(Employee.last_name, Employee.first_name).all())
        choices += [(e.id, e.full_name) for e in emps]
    return choices
```

In `create()` and `edit()`, right after `form = SalesOrderForm()`:

```python
    form.salesperson_id.choices = _salesperson_choices(session.get('selected_branch_id'))
```

In the `SalesOrder(...)` constructor (create) and the edit assignment block, set:

```python
        salesperson_id=(form.salesperson_id.data or None),
```

(For edit: `so.salesperson_id = form.salesperson_id.data or None`. `0` → falsy → `None`.)

- [ ] **Step 5: Render the gated picker in the form**

In `app/sales_orders/templates/sales_orders/form.html`, inside the header fields (near the Reference field), add:

```html
{% if module_enabled('employees') %}
<div class="form-group">
  <label class="form-label" for="salesperson_id">Salesperson</label>
  <select name="salesperson_id" id="salesperson_id" class="form-control">
    {% for val, label in form.salesperson_id.choices %}
      <option value="{{ val }}"
        {% if so and so.salesperson_id == val %}selected{% elif form.salesperson_id.data == val %}selected{% endif %}>{{ label }}</option>
    {% endfor %}
  </select>
</div>
{% endif %}
```

- [ ] **Step 6: Run the test + SO marker suite**

Run: `venv/Scripts/python.exe -m pytest "tests/integration/test_sales_orders_crud.py::test_so_persists_salesperson_when_employees_enabled" -p no:cov -v`
then `venv/Scripts/python.exe -m pytest -m sales_orders -p no:cov -q`
Expected: PASS both.

- [ ] **Step 7: Commit**

```bash
git add app/sales_orders/forms.py app/sales_orders/views.py \
        app/sales_orders/templates/sales_orders/form.html tests/integration/test_sales_orders_crud.py
git commit -m "feat(sales-orders): salesperson picker (Employee), gated on the Employees module"
```

---

### Task 3: Sales Invoice — salesperson picker (mirror of Task 2)

**Files:**
- Modify: `app/sales_invoices/forms.py::SalesInvoiceForm`, `app/sales_invoices/views.py` (create ~637 + edit ~769), `app/sales_invoices/templates/sales_invoices/form.html`
- Test: `tests/integration/test_sales_invoices.py`

**Interfaces:**
- Consumes: `SalesInvoice.salesperson_id` (Task 1).
- Produces: SI create/edit persists `salesperson_id`; gated picker.

- [ ] **Step 1: Write the failing test**

Add to `tests/integration/test_sales_invoices.py` a test mirroring Task 2 Step 1 (enable Employees, create an Employee, POST `/sales-invoices/create` with `salesperson_id`, assert the persisted `SalesInvoice.salesperson_id`). Reuse that file's existing SI create-payload helpers so the header/line fields match its working tests.

- [ ] **Step 2: Run to verify it fails**

Run: `venv/Scripts/python.exe -m pytest tests/integration/test_sales_invoices.py -k salesperson -p no:cov -v`
Expected: FAIL — view ignores `salesperson_id`.

- [ ] **Step 3: Add the form field**

In `app/sales_invoices/forms.py`, add to `SalesInvoiceForm`:

```python
    salesperson_id = SelectField('Salesperson', coerce=int, validators=[Optional()],
                                 validate_choice=False)
```

- [ ] **Step 4: Populate choices + persist**

In `app/sales_invoices/views.py`, add the same `_salesperson_choices(branch_id)` helper (or import it from `app.sales_orders.views`). In `create()` and `edit()`, after the customer choices are set:

```python
    form.salesperson_id.choices = _salesperson_choices(session.get('selected_branch_id'))
```

In the `SalesInvoice(...)` constructor add `salesperson_id=(form.salesperson_id.data or None),`; in `edit()` set `invoice.salesperson_id = form.salesperson_id.data or None`.

- [ ] **Step 5: Render the gated picker**

In `app/sales_invoices/templates/sales_invoices/form.html`, inside the header fields (near Reference), add the same `{% if module_enabled('employees') %}` picker block as Task 2 Step 5, keyed on `invoice`/`form.salesperson_id`.

- [ ] **Step 6: Run the test + SI marker suite**

Run: `venv/Scripts/python.exe -m pytest tests/integration/test_sales_invoices.py -k salesperson -p no:cov -v`
then `venv/Scripts/python.exe -m pytest -m sales_invoices -p no:cov -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add app/sales_invoices/forms.py app/sales_invoices/views.py \
        app/sales_invoices/templates/sales_invoices/form.html tests/integration/test_sales_invoices.py
git commit -m "feat(sales-invoices): salesperson picker (Employee), gated on the Employees module"
```

---

### Task 4: SI printouts + detail + pre-printed field

**Files:**
- Modify: `app/sales_invoices/templates/sales_invoices/print.html`, `detail.html`, `print_preprinted.html`, `app/sales_invoices/preprinted_layout.py`
- Test: `tests/integration/test_sales_invoices.py`

**Interfaces:**
- Consumes: `SalesInvoice.salesperson` (Task 1).

- [ ] **Step 1: Write the failing test**

Add to `tests/integration/test_sales_invoices.py`: create an SI with a salesperson (Employee), GET its `/print`, assert the employee `full_name` appears; create one without and assert the label renders with an empty value (no crash).

- [ ] **Step 2: Run to verify it fails**

Run: `venv/Scripts/python.exe -m pytest tests/integration/test_sales_invoices.py -k salesperson_print -p no:cov -v`
Expected: FAIL — the name is not rendered.

- [ ] **Step 3: Add the salesperson row to `print.html` + `detail.html`**

In `app/sales_invoices/templates/sales_invoices/print.html`, in the invoice-header table (near the `Invoice No.` row ~line 89), add:

```html
      <tr><td class="label">Salesperson</td><td>{{ invoice.salesperson.full_name if invoice.salesperson else '' }}</td></tr>
```

Add the equivalent labelled line to `detail.html` in its header block.

- [ ] **Step 4: Add `salesperson` to the pre-printed layout**

In `app/sales_invoices/preprinted_layout.py`, add `'salesperson'` to `FIELD_KEYS` (so the designer can place it). In `print_preprinted.html`, add a positioned element mirroring the other `.pp-el` header fields:

```html
<div class="pp-el" style="{{ pp_style(layout.fields.salesperson) }}">{{ invoice.salesperson.full_name if invoice.salesperson else '' }}</div>
```

(Use the same `pp_style`/positioning helper the sibling fields use; blank when unset.)

- [ ] **Step 5: Run the test + SI marker suite**

Run: `venv/Scripts/python.exe -m pytest tests/integration/test_sales_invoices.py -k salesperson -p no:cov -v`
then `venv/Scripts/python.exe -m pytest -m sales_invoices -p no:cov -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/sales_invoices/templates/sales_invoices/print.html \
        app/sales_invoices/templates/sales_invoices/detail.html \
        app/sales_invoices/templates/sales_invoices/print_preprinted.html \
        app/sales_invoices/preprinted_layout.py tests/integration/test_sales_invoices.py
git commit -m "feat(sales-invoices): show salesperson on SI print/detail + pre-printed form field"
```

---

## Post-implementation

- Browser-verify (Employees enabled + an employee seeded): the SO and SI forms show a Salesperson picker; a saved SI's `/print` shows the name; the pre-printed designer offers a Salesperson field.
- Confirm the picker is absent when the Employees module is disabled, and create still succeeds (salesperson null).
- `/guard` before pushing (SO/SI models + templates are blast-radius).
- Follow-ups (own slices): DR salesperson field + the SO→DR→SI auto-fill cascade (`copy_salesperson` hook), sales-by-agent reporting, and the Order-Monitoring "by salesperson" breakdown.
