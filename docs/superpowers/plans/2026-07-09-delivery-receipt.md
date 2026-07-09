# Delivery Receipt Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Delivery Receipt document that records deliveries against a confirmed Sales Order — operational-only, partial deliveries (1 SO → many DRs) with a cumulative-delivered ≤ ordered guard, and a draft→approved→delivered→billed→cancelled lifecycle.

**Architecture:** A new `app/delivery_receipts/` blueprint mirroring the `sales_orders` package. Two tables (`delivery_receipts` header + `delivery_receipt_items` lines), each DR line referencing a `sales_order_item` and carrying a `delivered_quantity`. The ordered-qty guard is enforced at the `approve` transition. No journal entry (an inert `post_delivery_je` seam is reserved for R-03).

**Tech Stack:** Flask + SQLAlchemy + SQLite; Flask-Migrate/Alembic (hand-written batch, `render_as_batch` OFF); pytest (`-p no:cov`, single-threaded `-n0` for the guard tests).

## Global Constraints

- **DR always references a confirmed SO** (never standalone); a DR line references a `sales_order_item`; product/uom/unit_price are READ through that relationship (no duplication).
- **Operational-only — no journal entry.** `post_delivery_je(dr)` is a documented no-op seam for R-03; never called by a transition.
- **Lifecycle:** `draft → approved → delivered → billed`, plus `cancelled`. **Lock at approved** (only draft is editable). **Commit qty at approved** (draft does NOT consume SO open qty). **Cancel releases** committed qty.
- **The guard:** cumulative `delivered_quantity` across DR lines referencing one SO line whose DR status ∈ {approved, delivered, billed} must be **≤ that SO line's ordered quantity**; enforced at `approve`, raising `ValueError` (flashed verbatim, DR stays draft).
- **Module:** `delivery_receipts` — `optional`, `depends_on: ['sales_orders']`, `per_user`, `default_enabled: False`, branch-scoped.
- **Numbering:** `DR-YYYY-MM-####` per branch/month.
- **Approve gate:** the Approver role is a SEPARATE spec; **interim-gate `approve` to `['accountant', 'admin', 'chief_accountant']`** and leave a `# TODO(Approver role)` note at the gate.
- **Salesperson** carried from the SO via `copy_salesperson` (from `app.sales_orders.models`), gated on the Employees module.
- **OUT OF SCOPE:** DR→SI billing flow (only the `sales_invoice_id`+`billed` seam here), the Approver role, R-03 COGS, the pre-printed designer.

---

### Task 1: Models + migration + registration

**Files:**
- Create: `app/delivery_receipts/__init__.py` (empty), `app/delivery_receipts/models.py`
- Create: `migrations/versions/<generated>_add_delivery_receipts.py`
- Modify: `app/__init__.py` (register models ~line 212, near `from app.sales_orders.models import ...`)
- Test: `tests/unit/test_delivery_receipt_model.py`

**Interfaces:**
- Produces: `DeliveryReceipt` (header) + `DeliveryReceiptItem` (line) models; module-level
  `so_line_open_qty(so_item, exclude_dr_id=None) -> Decimal`, `generate_dr_number(branch_id) -> str`,
  `post_delivery_je(dr) -> None`. `COMMITTED_STATUSES = ('approved', 'delivered', 'billed')`.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_delivery_receipt_model.py`:

```python
import pytest
from datetime import date
from decimal import Decimal
from app import db
from app.customers.models import Customer
from app.products.models import Product
from app.sales_orders.models import SalesOrder, SalesOrderItem
from app.delivery_receipts.models import (
    DeliveryReceipt, DeliveryReceiptItem, so_line_open_qty, post_delivery_je)

pytestmark = [pytest.mark.integration, pytest.mark.delivery_receipts]


def _so_with_line(db_session, branch_id, ordered='10'):
    c = Customer(code='C-DR', name='DR Corp', is_active=True)
    p = Product(code='W', name='Widget', is_active=True)
    db.session.add_all([c, p]); db.session.commit()
    so = SalesOrder(so_number='SO-DR-1', order_date=date(2026, 7, 9), customer_id=c.id,
                    customer_name='DR Corp', branch_id=branch_id, status='confirmed')
    li = SalesOrderItem(line_number=1, product_id=p.id, quantity=Decimal(ordered),
                        unit_price=Decimal('100'), amount=Decimal('1000'))
    so.line_items.append(li)
    db.session.add(so); db.session.commit()
    return so, li


def _dr(db_session, so, so_item, branch_id, qty, status):
    dr = DeliveryReceipt(dr_number=f'DR-T-{status}-{qty}', branch_id=branch_id,
                         sales_order_id=so.id, customer_id=so.customer_id,
                         customer_name=so.customer_name, delivery_date=date(2026, 7, 9),
                         status=status)
    dr.line_items.append(DeliveryReceiptItem(line_number=1, sales_order_item_id=so_item.id,
                                             product_id=so_item.product_id,
                                             delivered_quantity=Decimal(qty)))
    db.session.add(dr); db.session.commit()
    return dr


def test_open_qty_ignores_draft_counts_committed_releases_cancelled(db_session, main_branch):
    so, li = _so_with_line(db_session, main_branch.id, ordered='10')
    assert so_line_open_qty(li) == Decimal('10')          # nothing delivered yet
    _dr(db_session, so, li, main_branch.id, '3', 'draft')   # draft -> does NOT count
    assert so_line_open_qty(li) == Decimal('10')
    _dr(db_session, so, li, main_branch.id, '4', 'approved')  # committed
    assert so_line_open_qty(li) == Decimal('6')
    cancelled = _dr(db_session, so, li, main_branch.id, '2', 'cancelled')  # released
    assert so_line_open_qty(li) == Decimal('6')


def test_to_dict_and_post_seam(db_session, main_branch):
    so, li = _so_with_line(db_session, main_branch.id)
    dr = _dr(db_session, so, li, main_branch.id, '5', 'draft')
    d = dr.to_dict()
    assert d['status'] == 'draft' and d['sales_order_number'] == 'SO-DR-1'
    assert dr.line_items[0].to_dict()['delivered_quantity'] == 5.0
    assert dr.line_items[0].to_dict()['ordered_quantity'] == 10.0
    assert post_delivery_je(dr) is None      # inert R-03 seam
```

- [ ] **Step 2: Run to verify it fails**

Run: `venv/Scripts/python.exe -m pytest tests/unit/test_delivery_receipt_model.py -p no:cov -v`
Expected: FAIL — `No module named 'app.delivery_receipts'`.

- [ ] **Step 3: Create the package + models**

Create `app/delivery_receipts/__init__.py` (empty file).

Create `app/delivery_receipts/models.py`:

```python
"""Delivery Receipt — records deliveries against a confirmed Sales Order.
Operational, NOT accounting: posts no journal entry. Middle link of SO -> DR -> SI.
"""
from decimal import Decimal
from app import db
from app.utils import ph_now

# DR statuses that CONSUME the SO's open quantity (draft & cancelled do not).
COMMITTED_STATUSES = ('approved', 'delivered', 'billed')


class DeliveryReceipt(db.Model):
    __tablename__ = 'delivery_receipts'

    id = db.Column(db.Integer, primary_key=True)
    branch_id = db.Column(db.Integer, db.ForeignKey('branches.id'), nullable=True, index=True)
    branch = db.relationship('Branch', foreign_keys=[branch_id])

    dr_number = db.Column(db.String(50), unique=True, nullable=False, index=True)
    delivery_date = db.Column(db.Date, nullable=False, index=True)

    sales_order_id = db.Column(db.Integer, db.ForeignKey('sales_orders.id'), nullable=False, index=True)
    sales_order = db.relationship('SalesOrder', foreign_keys=[sales_order_id])

    # Customer snapshot (from the SO at create; no picker).
    customer_id = db.Column(db.Integer, db.ForeignKey('customers.id'), nullable=False, index=True)
    customer_name = db.Column(db.String(200), nullable=False)

    status = db.Column(db.String(20), default='draft', nullable=False, index=True)
    remarks = db.Column(db.Text)

    salesperson_id = db.Column(db.Integer, db.ForeignKey('employees.id'), nullable=True, index=True)
    salesperson = db.relationship('Employee', foreign_keys=[salesperson_id])

    # Billing seam (sub-project #2 fills this); null/false until billed.
    sales_invoice_id = db.Column(db.Integer, db.ForeignKey('sales_invoices.id'), nullable=True, index=True)

    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=ph_now, nullable=False)
    updated_at = db.Column(db.DateTime, default=ph_now, onupdate=ph_now, nullable=False)
    approved_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    approved_at = db.Column(db.DateTime)
    delivered_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    delivered_at = db.Column(db.DateTime)
    cancelled_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    cancelled_at = db.Column(db.DateTime)
    cancel_reason = db.Column(db.String(500))

    line_items = db.relationship('DeliveryReceiptItem', backref='delivery_receipt',
                                 lazy='select', cascade='all, delete-orphan',
                                 order_by='DeliveryReceiptItem.line_number')

    def to_dict(self):
        return {
            'id': self.id, 'dr_number': self.dr_number, 'status': self.status,
            'delivery_date': self.delivery_date.isoformat() if self.delivery_date else None,
            'sales_order_id': self.sales_order_id,
            'sales_order_number': self.sales_order.so_number if self.sales_order else None,
            'customer_name': self.customer_name,
            'salesperson_id': self.salesperson_id,
            'salesperson_name': self.salesperson.full_name if self.salesperson else None,
        }


class DeliveryReceiptItem(db.Model):
    __tablename__ = 'delivery_receipt_items'

    id = db.Column(db.Integer, primary_key=True)
    delivery_receipt_id = db.Column(db.Integer, db.ForeignKey('delivery_receipts.id'),
                                    nullable=False, index=True)
    line_number = db.Column(db.Integer, nullable=False)
    sales_order_item_id = db.Column(db.Integer, db.ForeignKey('sales_order_items.id'),
                                    nullable=False, index=True)
    sales_order_item = db.relationship('SalesOrderItem', foreign_keys=[sales_order_item_id])
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=True)  # snapshot for print
    product = db.relationship('Product', foreign_keys=[product_id])
    delivered_quantity = db.Column(db.Numeric(15, 4), nullable=False)

    def to_dict(self):
        soi = self.sales_order_item
        return {
            'id': self.id, 'line_number': self.line_number,
            'sales_order_item_id': self.sales_order_item_id,
            'delivered_quantity': float(self.delivered_quantity) if self.delivered_quantity is not None else 0.0,
            'ordered_quantity': float(soi.quantity) if (soi and soi.quantity is not None) else None,
            'product_code': soi.product.code if (soi and soi.product) else (self.product.code if self.product else None),
            'product_name': soi.product.name if (soi and soi.product) else (self.product.name if self.product else None),
            'uom': (soi.unit_of_measure.code if (soi and soi.unit_of_measure) else (soi.uom_text if soi else None)),
            'unit_price': float(soi.unit_price) if (soi and soi.unit_price is not None) else None,
        }


def so_line_open_qty(so_item, exclude_dr_id=None):
    """Ordered qty of an SO line minus the qty already committed by non-cancelled,
    non-draft DR lines (statuses in COMMITTED_STATUSES). Pass exclude_dr_id to leave
    a specific DR out of the sum (used when re-checking the DR being approved)."""
    ordered = Decimal(str(so_item.quantity or 0))
    q = (db.session.query(db.func.coalesce(db.func.sum(DeliveryReceiptItem.delivered_quantity), 0))
         .join(DeliveryReceipt, DeliveryReceiptItem.delivery_receipt_id == DeliveryReceipt.id)
         .filter(DeliveryReceiptItem.sales_order_item_id == so_item.id)
         .filter(DeliveryReceipt.status.in_(COMMITTED_STATUSES)))
    if exclude_dr_id is not None:
        q = q.filter(DeliveryReceipt.id != exclude_dr_id)
    committed = Decimal(str(q.scalar() or 0))
    return ordered - committed


def generate_dr_number(branch_id):
    """Next DR-YYYY-MM-#### for the current PH month (mirror generate_so_number)."""
    from app.utils import ph_now
    today = ph_now().date()
    prefix = f"DR-{today.year:04d}-{today.month:02d}-"
    rows = (DeliveryReceipt.query.filter(DeliveryReceipt.dr_number.like(prefix + '%'))
            .with_entities(DeliveryReceipt.dr_number).all())
    nums = []
    for (n,) in rows:
        tail = n.rsplit('-', 1)[-1]
        if tail.isdigit():
            nums.append(int(tail))
    return f"{prefix}{(max(nums) + 1) if nums else 1:04d}"


def post_delivery_je(dr):
    """R-03 seam: on-delivery inventory-relief / COGS journal entry. Inert now (no-op)."""
    return None
```

- [ ] **Step 4: Register the models in `create_app`**

In `app/__init__.py`, next to `from app.sales_orders.models import SalesOrder, SalesOrderItem` (~line 212), add:

```python
    from app.delivery_receipts.models import DeliveryReceipt, DeliveryReceiptItem
```

- [ ] **Step 5: Run the model test**

Run: `venv/Scripts/python.exe -m pytest tests/unit/test_delivery_receipt_model.py -p no:cov -v`
Expected: PASS (conftest `create_all()` builds the new tables from the models).

- [ ] **Step 6: Scaffold + write the migration**

Run: `venv/Scripts/python.exe -m flask db revision -m "add delivery_receipts and items"`

Replace the body (2 `create_table`s; `down_revision` is auto-set to the current head):

```python
def upgrade():
    op.create_table('delivery_receipts',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('branch_id', sa.Integer(), sa.ForeignKey('branches.id'), nullable=True),
        sa.Column('dr_number', sa.String(length=50), nullable=False),
        sa.Column('delivery_date', sa.Date(), nullable=False),
        sa.Column('sales_order_id', sa.Integer(), sa.ForeignKey('sales_orders.id'), nullable=False),
        sa.Column('customer_id', sa.Integer(), sa.ForeignKey('customers.id'), nullable=False),
        sa.Column('customer_name', sa.String(length=200), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='draft'),
        sa.Column('remarks', sa.Text(), nullable=True),
        sa.Column('salesperson_id', sa.Integer(), sa.ForeignKey('employees.id'), nullable=True),
        sa.Column('sales_invoice_id', sa.Integer(), sa.ForeignKey('sales_invoices.id'), nullable=True),
        sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('approved_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('approved_at', sa.DateTime(), nullable=True),
        sa.Column('delivered_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('delivered_at', sa.DateTime(), nullable=True),
        sa.Column('cancelled_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('cancelled_at', sa.DateTime(), nullable=True),
        sa.Column('cancel_reason', sa.String(length=500), nullable=True),
    )
    with op.batch_alter_table('delivery_receipts', schema=None) as b:
        b.create_index('ix_delivery_receipts_dr_number', ['dr_number'], unique=True)
        b.create_index('ix_delivery_receipts_branch_id', ['branch_id'])
        b.create_index('ix_delivery_receipts_sales_order_id', ['sales_order_id'])
        b.create_index('ix_delivery_receipts_status', ['status'])
        b.create_index('ix_delivery_receipts_delivery_date', ['delivery_date'])

    op.create_table('delivery_receipt_items',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('delivery_receipt_id', sa.Integer(), sa.ForeignKey('delivery_receipts.id'), nullable=False),
        sa.Column('line_number', sa.Integer(), nullable=False),
        sa.Column('sales_order_item_id', sa.Integer(), sa.ForeignKey('sales_order_items.id'), nullable=False),
        sa.Column('product_id', sa.Integer(), sa.ForeignKey('products.id'), nullable=True),
        sa.Column('delivered_quantity', sa.Numeric(15, 4), nullable=False),
    )
    with op.batch_alter_table('delivery_receipt_items', schema=None) as b:
        b.create_index('ix_delivery_receipt_items_delivery_receipt_id', ['delivery_receipt_id'])
        b.create_index('ix_delivery_receipt_items_sales_order_item_id', ['sales_order_item_id'])


def downgrade():
    op.drop_table('delivery_receipt_items')
    op.drop_table('delivery_receipts')
```

- [ ] **Step 7: Verify the migration on a copy of cas.db, then apply**

```bash
cp instance/cas.db instance/_x.db
SQLALCHEMY_DATABASE_URI=sqlite:///_x.db venv/Scripts/python.exe -m flask db upgrade
venv/Scripts/python.exe -c "import sqlite3; c=sqlite3.connect('instance/_x.db'); \
t=[r[0] for r in c.execute(\"SELECT name FROM sqlite_master WHERE type='table'\")]; \
print('delivery_receipts' in t, 'delivery_receipt_items' in t)"
rm -f instance/_x.db
venv/Scripts/python.exe -m flask db upgrade
```

Expected: prints `True True`; demo DB upgrade clean.

- [ ] **Step 8: Commit**

```bash
git add app/delivery_receipts/__init__.py app/delivery_receipts/models.py app/__init__.py \
        migrations/versions/*add_delivery_receipts*.py tests/unit/test_delivery_receipt_model.py
git commit -m "feat(delivery-receipts): DR + item models, open-qty helper, numbering, R-03 seam, migration"
```

---

### Task 2: Module registry + blueprint + nav gating

**Files:**
- Create: `app/delivery_receipts/views.py` (blueprint + a stub `list` route for now)
- Modify: `app/users/module_access.py` (registry entry, after the `sales_orders` entry ~line 20),
  `app/__init__.py` (blueprint import ~line 243 + register ~line 260-ish),
  `app/templates/base.html` (nav route/icon/subtext dicts ~1052/1076/1141)
- Test: `tests/integration/test_delivery_receipts_gate.py`

**Interfaces:**
- Consumes: nothing from Task 1 except the package.
- Produces: `delivery_receipts_bp` blueprint; `delivery_receipts.list` route; the `delivery_receipts`
  module gate.

- [ ] **Step 1: Write the failing test**

Create `tests/integration/test_delivery_receipts_gate.py`:

```python
import pytest

pytestmark = [pytest.mark.integration, pytest.mark.delivery_receipts]


def _login(client, user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id); sess['_fresh'] = True


def _enable(db_session, *keys):
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    for k in keys:
        AppSettings.set_setting(f'module_enabled:{k}', '1')
    db_session.commit(); clear_module_config_cache()


def test_dr_list_blocked_when_module_off(client, db_session, admin_user, main_branch):
    _login(client, admin_user)
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = main_branch.id
    resp = client.get('/delivery-receipts', follow_redirects=False)
    assert resp.status_code in (302, 403)         # gated off by default


def test_dr_registry_entry_is_optional_products_gated_per_user(db_session):
    from app.users.module_access import MODULE_REGISTRY, all_permission_keys
    e = next(m for m in MODULE_REGISTRY if m['key'] == 'delivery_receipts')
    assert e['optional'] is True and e['per_user'] is True
    assert e['default_enabled'] is False and e['depends_on'] == ['sales_orders']
    assert 'delivery_receipts' in all_permission_keys()   # per_user keeps it in the grid


def test_dr_list_ok_when_enabled(client, db_session, admin_user, main_branch):
    _enable(db_session, 'delivery_receipts')
    _login(client, admin_user)
    with client.session_transaction() as sess:
        sess['selected_branch_id'] = main_branch.id
    assert client.get('/delivery-receipts').status_code == 200
```

- [ ] **Step 2: Run to verify it fails**

Run: `venv/Scripts/python.exe -m pytest tests/integration/test_delivery_receipts_gate.py -p no:cov -v`
Expected: FAIL — no route / no registry entry.

- [ ] **Step 3: Create the blueprint with a stub list route**

Create `app/delivery_receipts/views.py`:

```python
"""Delivery Receipt views — deliveries against a confirmed Sales Order. Operational only."""
from flask import Blueprint, render_template, redirect, url_for, flash, request, session, abort
from flask_login import login_required, current_user
from app import db
from app.delivery_receipts.models import DeliveryReceipt

delivery_receipts_bp = Blueprint('delivery_receipts', __name__, template_folder='templates')

VALID_DR_STATUSES = {'draft', 'approved', 'delivered', 'billed', 'cancelled'}


@delivery_receipts_bp.route('/delivery-receipts')
@login_required
def list():
    branch_id = session.get('selected_branch_id')
    query = DeliveryReceipt.query.filter_by(branch_id=branch_id)
    status_filter = request.args.get('status', 'all')
    if status_filter in VALID_DR_STATUSES:
        query = query.filter_by(status=status_filter)
    receipts = query.order_by(DeliveryReceipt.delivery_date.desc(),
                              DeliveryReceipt.id.desc()).all()
    return render_template('delivery_receipts/list.html', receipts=receipts,
                           status_filter=status_filter)
```

Create `app/delivery_receipts/templates/delivery_receipts/list.html`:

```html
{% extends "base.html" %}
{% block title %}Delivery Receipts{% endblock %}
{% block content %}
<div class="page-header" style="display:flex; justify-content:space-between; align-items:center;">
  <h1>Delivery Receipts</h1>
  <a href="{{ url_for('sales_orders.list') }}" class="btn btn-secondary btn-sm">Sales Orders</a>
</div>
<div class="card"><div class="card-body">
  {% if receipts %}
  <table class="table"><thead><tr><th>DR #</th><th>Date</th><th>Customer</th><th>SO #</th><th>Status</th></tr></thead>
    <tbody>{% for dr in receipts %}
      <tr>
        <td><a href="{{ url_for('delivery_receipts.view', id=dr.id) }}">{{ dr.dr_number }}</a></td>
        <td>{{ dr.delivery_date.strftime('%b %d, %Y') }}</td>
        <td>{{ dr.customer_name }}</td>
        <td>{{ dr.sales_order.so_number if dr.sales_order else '' }}</td>
        <td><span class="badge badge-{{ 'secondary' if dr.status=='draft' else 'success' if dr.status in ('approved','delivered') else 'info' if dr.status=='billed' else 'danger' }}">{{ dr.status|title }}</span></td>
      </tr>
    {% endfor %}</tbody></table>
  {% else %}<p>No delivery receipts found.</p>{% endif %}
</div></div>
{% endblock %}
```

(`view` route is added in Task 3; the list link is inert until then, which is fine — the gate test
only GETs `/delivery-receipts`.)

- [ ] **Step 4: Add the module registry entry**

In `app/users/module_access.py`, immediately after the `sales_orders` entry, add:

```python
    {'key': 'delivery_receipts', 'label': 'Delivery Receipts', 'section': 'Transactions',
     'area': 'Sales', 'group': 'Documents',
     'optional': True, 'depends_on': ['sales_orders'], 'default_enabled': False, 'per_user': True,
     'endpoints': ('delivery_receipts.',)},
```

- [ ] **Step 5: Register the blueprint**

In `app/__init__.py`, near `from app.sales_orders.views import sales_orders_bp` (~line 243) add:

```python
    from app.delivery_receipts.views import delivery_receipts_bp
```
and near `app.register_blueprint(sales_invoices_bp)` add:

```python
    app.register_blueprint(delivery_receipts_bp)
```

- [ ] **Step 6: Wire the sidebar nav**

In `app/templates/base.html`, add `delivery_receipts` to the three data dicts (mirror `sales_orders`):
- routes dict (~line 1052): `'delivery_receipts': 'delivery_receipts.list',`
- icons dict (~line 1076): `'delivery_receipts': '🚚',`
- (optional subtext, ~line 1141): `{%- if m.key == 'delivery_receipts' %}<span class="nav-subtext">(Deliveries)</span>{% endif %}`

- [ ] **Step 7: Run the gate test**

Run: `venv/Scripts/python.exe -m pytest tests/integration/test_delivery_receipts_gate.py -p no:cov -v`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add app/delivery_receipts/views.py app/delivery_receipts/templates/ \
        app/users/module_access.py app/__init__.py app/templates/base.html \
        tests/integration/test_delivery_receipts_gate.py
git commit -m "feat(delivery-receipts): optional module (depends_on sales_orders) + blueprint + nav + list"
```

---

### Task 3: Create / view / edit a draft DR against an SO

**Files:**
- Create: `app/delivery_receipts/forms.py`, templates `form.html`, `detail.html`
- Modify: `app/delivery_receipts/views.py` (add `create`, `view`, `edit`, helpers)
- Test: `tests/integration/test_delivery_receipts_crud.py`

**Interfaces:**
- Consumes: `so_line_open_qty`, `generate_dr_number` (Task 1); `copy_salesperson` from
  `app.sales_orders.models`.
- Produces: `delivery_receipts.create`, `.view`, `.edit`; helper `_eligible_sales_orders(branch_id)`
  (confirmed SOs with ≥1 line still open) and `_dr_role_gate()`.

- [ ] **Step 1: Write the failing test**

Add `tests/integration/test_delivery_receipts_crud.py`:

```python
import json, pytest
from datetime import date
from decimal import Decimal
from app import db
from app.customers.models import Customer
from app.products.models import Product
from app.sales_orders.models import SalesOrder, SalesOrderItem
from app.delivery_receipts.models import DeliveryReceipt

pytestmark = [pytest.mark.integration, pytest.mark.delivery_receipts]


@pytest.fixture(autouse=True)
def dr_enabled(db_session):
    from app.settings import AppSettings
    from app.utils.cache_helpers import clear_module_config_cache
    AppSettings.set_setting('module_enabled:delivery_receipts', '1')
    db_session.commit(); clear_module_config_cache()
    yield; clear_module_config_cache()


def _login(client, u):
    with client.session_transaction() as s:
        s['_user_id'] = str(u.id); s['_fresh'] = True


def _confirmed_so(db_session, branch_id):
    c = Customer(code='C1', name='Acme', is_active=True)
    p = Product(code='W', name='Widget', is_active=True)
    db.session.add_all([c, p]); db.session.commit()
    so = SalesOrder(so_number='SO-C-1', order_date=date(2026, 7, 9), customer_id=c.id,
                    customer_name='Acme', branch_id=branch_id, status='confirmed')
    so.line_items.append(SalesOrderItem(line_number=1, product_id=p.id, quantity=Decimal('10'),
                                        unit_price=Decimal('100'), amount=Decimal('1000')))
    db.session.add(so); db.session.commit()
    return so


def test_create_draft_dr_persists_and_snapshots_customer(client, db_session, admin_user, main_branch):
    so = _confirmed_so(db_session, main_branch.id)
    _login(client, admin_user)
    with client.session_transaction() as s: s['selected_branch_id'] = main_branch.id
    lines = json.dumps([{'sales_order_item_id': so.line_items[0].id, 'delivered_quantity': '4'}])
    client.post('/delivery-receipts/create', data={
        'sales_order_id': so.id, 'delivery_date': '2026-07-09', 'lines': lines},
        follow_redirects=True)
    dr = DeliveryReceipt.query.filter_by(sales_order_id=so.id).first()
    assert dr is not None and dr.status == 'draft'
    assert dr.customer_name == 'Acme' and dr.customer_id == so.customer_id
    assert dr.line_items[0].delivered_quantity == Decimal('4')
```

- [ ] **Step 2: Run to verify it fails**

Run: `venv/Scripts/python.exe -m pytest tests/integration/test_delivery_receipts_crud.py -p no:cov -v`
Expected: FAIL — no `create` route.

- [ ] **Step 3: Add the form**

Create `app/delivery_receipts/forms.py`:

```python
from flask_wtf import FlaskForm
from wtforms import SelectField, DateField, TextAreaField, HiddenField
from wtforms.validators import DataRequired, Optional
from datetime import date


class DeliveryReceiptForm(FlaskForm):
    sales_order_id = SelectField('Sales Order', coerce=int, validators=[DataRequired()],
                                 validate_choice=False)
    delivery_date = DateField('Delivery Date', validators=[DataRequired()],
                              format='%Y-%m-%d', default=date.today)
    salesperson_id = SelectField('Salesperson', coerce=int, validators=[Optional()],
                                 validate_choice=False)
    remarks = TextAreaField('Remarks', validators=[Optional()])
    lines = HiddenField('Lines JSON')
```

- [ ] **Step 4: Add create/view/edit + helpers to `views.py`**

Add these imports at the top of `app/delivery_receipts/views.py`:

```python
import json
from datetime import date
from decimal import Decimal, InvalidOperation
from app.delivery_receipts.models import (
    DeliveryReceiptItem, so_line_open_qty, generate_dr_number)
from app.delivery_receipts.forms import DeliveryReceiptForm
from app.sales_orders.models import SalesOrder, SalesOrderItem, copy_salesperson
from app.audit.utils import log_create, model_to_dict
from app.utils import ph_now
```

Add the helpers + routes:

```python
def _dr_role_gate():
    if current_user.role not in ['staff', 'accountant', 'admin', 'chief_accountant']:
        flash('You do not have permission to manage Delivery Receipts.', 'error')
        return redirect(url_for('delivery_receipts.list'))
    return None


def _eligible_sales_orders(branch_id):
    """Confirmed SOs in this branch that still have at least one line with open qty."""
    sos = SalesOrder.query.filter_by(branch_id=branch_id, status='confirmed').all()
    return [so for so in sos if any(so_line_open_qty(li) > 0 for li in so.line_items)]


def _salesperson_choices(branch_id):
    from app.sales_orders.views import _salesperson_choices as so_choices
    return so_choices(branch_id)


def _parse_dr_lines(dr, lines_json):
    """Attach DR lines from the hidden JSON: [{sales_order_item_id, delivered_quantity}]."""
    items = json.loads(lines_json) if lines_json else []
    kept = 0
    for d in items:
        try:
            qty = Decimal(str(d.get('delivered_quantity')))
        except (InvalidOperation, TypeError):
            qty = Decimal('0')
        soi_id = d.get('sales_order_item_id')
        if not soi_id or qty <= 0:
            continue
        kept += 1
        soi = db.session.get(SalesOrderItem, int(soi_id))
        dr.line_items.append(DeliveryReceiptItem(
            line_number=kept, sales_order_item_id=int(soi_id),
            product_id=(soi.product_id if soi else None),
            delivered_quantity=qty))
    if kept == 0:
        raise ValueError('Add at least one delivered line.')


@delivery_receipts_bp.route('/delivery-receipts/create', methods=['GET', 'POST'])
@login_required
def create():
    gate = _dr_role_gate()
    if gate:
        return gate
    branch_id = session.get('selected_branch_id')
    form = DeliveryReceiptForm()
    eligible = _eligible_sales_orders(branch_id)
    form.sales_order_id.choices = [(so.id, so.so_number) for so in eligible]
    form.salesperson_id.choices = _salesperson_choices(branch_id)

    if form.validate_on_submit():
        so = db.session.get(SalesOrder, form.sales_order_id.data)
        if not so or so.branch_id != branch_id or so.status != 'confirmed':
            flash('Select a valid confirmed Sales Order.', 'error')
            return render_template('delivery_receipts/form.html', form=form, dr=None,
                                   eligible=eligible)
        try:
            dr = DeliveryReceipt(
                dr_number=generate_dr_number(branch_id), branch_id=branch_id,
                delivery_date=form.delivery_date.data, sales_order_id=so.id,
                customer_id=so.customer_id, customer_name=so.customer_name,
                remarks=form.remarks.data or None, status='draft',
                created_by_id=current_user.id)
            copy_salesperson(so, dr)
            if form.salesperson_id.data:   # allow override
                dr.salesperson_id = form.salesperson_id.data
            _parse_dr_lines(dr, request.form.get('lines', '[]'))
            db.session.add(dr); db.session.commit()
            log_create(module='delivery_receipts', record_id=dr.id,
                       record_identifier=f'{dr.dr_number} - {dr.customer_name}',
                       new_values=model_to_dict(dr, ['dr_number', 'status', 'delivery_date']))
            flash(f'Delivery Receipt "{dr.dr_number}" created.', 'success')
            return redirect(url_for('delivery_receipts.view', id=dr.id))
        except ValueError as e:
            db.session.rollback(); flash(str(e), 'error')
        except Exception:
            db.session.rollback(); flash('An error occurred creating the Delivery Receipt.', 'error')

    if request.method == 'GET':
        form.delivery_date.data = ph_now().date()
    return render_template('delivery_receipts/form.html', form=form, dr=None, eligible=eligible)


@delivery_receipts_bp.route('/delivery-receipts/<int:id>')
@login_required
def view(id):
    dr = db.get_or_404(DeliveryReceipt, id)
    if dr.branch_id != session.get('selected_branch_id'):
        abort(404)
    return render_template('delivery_receipts/detail.html', dr=dr)
```

(For the create form's per-SO open-qty grid, `form.html` fetches the picked SO's lines with
`so_line_open_qty` via a small `{{ eligible }}`-driven `<script>` data blob — mirror the SO form's
line-grid JS: on SO-select, render its lines with product · ordered · already-delivered · **open** ·
a *deliver-now* number input, and serialize `{sales_order_item_id, delivered_quantity}` into the
`lines` hidden field. An `edit` route (draft only, same shape) is included here mirroring
`sales_orders.edit`.)

- [ ] **Step 5: Create `form.html` + `detail.html`**

`detail.html` renders the header (DR #, date, customer, SO #, salesperson, status badge) + a line
table (product · delivered qty via `{{ item | qty_fmt }}` · uom · ordered) + the action buttons
(Approve / Mark Delivered / Cancel — wired in Task 4) gated by `dr.status`. `form.html` is the
SO-select + open-qty line grid described above. Both extend `base.html`. **No peso glyph.**

- [ ] **Step 6: Run the create test + verify draft persists**

Run: `venv/Scripts/python.exe -m pytest tests/integration/test_delivery_receipts_crud.py -p no:cov -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add app/delivery_receipts/forms.py app/delivery_receipts/views.py \
        app/delivery_receipts/templates/ tests/integration/test_delivery_receipts_crud.py
git commit -m "feat(delivery-receipts): create draft DR against a confirmed SO (open-qty grid, salesperson carry)"
```

---

### Task 4: Lifecycle transitions + the ordered-qty guard (the core)

**Files:**
- Modify: `app/delivery_receipts/views.py` (add `approve`, `mark_delivered`, `cancel`; edit-lock)
- Test: `tests/integration/test_delivery_receipts_lifecycle.py`

**Interfaces:**
- Consumes: `so_line_open_qty` (Task 1), the draft-create flow (Task 3).
- Produces: `delivery_receipts.approve`, `.mark_delivered`, `.cancel`.

- [ ] **Step 1: Write the failing tests**

Create `tests/integration/test_delivery_receipts_lifecycle.py` — reuse the CRUD test's `dr_enabled`
fixture + `_confirmed_so` + `_login`. Cover:
- **Guard at approve:** create a draft DR delivering 4 of an ordered-10 line, approve → status
  `approved`; create a second draft delivering 7 (4 already committed → open 6), approve → **rejected**
  (stays draft, flash "exceeds the open quantity"); a third delivering 6 → approved OK.
- **Draft doesn't consume:** with a draft delivering 4 (un-approved), `so_line_open_qty` still 10.
- **Cancel releases:** approve the 4, open becomes 6; cancel it (reason) → open back to 10.
- **Lock at approved:** GET `/delivery-receipts/<id>/edit` on an approved DR → redirect, unchanged.
- **Approve role gate:** a `staff_user` POSTing approve is refused (interim gate = accountant/admin).

```python
def test_approve_guard_rejects_over_open_qty(client, db_session, admin_user, main_branch):
    so = _confirmed_so(db_session, main_branch.id)
    soi = so.line_items[0]
    _login(client, admin_user)
    with client.session_transaction() as s: s['selected_branch_id'] = main_branch.id
    # DR#1 delivers 4, approve OK
    lines1 = json.dumps([{'sales_order_item_id': soi.id, 'delivered_quantity': '4'}])
    client.post('/delivery-receipts/create', data={'sales_order_id': so.id,
        'delivery_date': '2026-07-09', 'lines': lines1}, follow_redirects=True)
    dr1 = DeliveryReceipt.query.order_by(DeliveryReceipt.id.desc()).first()
    client.post(f'/delivery-receipts/{dr1.id}/approve', follow_redirects=True)
    db_session.refresh(dr1); assert dr1.status == 'approved'
    # DR#2 delivers 7 (open now 6) -> approve REJECTED
    lines2 = json.dumps([{'sales_order_item_id': soi.id, 'delivered_quantity': '7'}])
    client.post('/delivery-receipts/create', data={'sales_order_id': so.id,
        'delivery_date': '2026-07-09', 'lines': lines2}, follow_redirects=True)
    dr2 = DeliveryReceipt.query.order_by(DeliveryReceipt.id.desc()).first()
    resp = client.post(f'/delivery-receipts/{dr2.id}/approve', follow_redirects=True)
    db_session.refresh(dr2)
    assert dr2.status == 'draft' and b'exceeds the open quantity' in resp.data
```

- [ ] **Step 2: Run to verify it fails**

Run: `venv/Scripts/python.exe -m pytest tests/integration/test_delivery_receipts_lifecycle.py -p no:cov -n0 -v`
Expected: FAIL — no `approve` route.

- [ ] **Step 3: Implement the transitions + guard**

Add to `app/delivery_receipts/views.py`:

```python
from app.audit.utils import log_audit


def _approve_role_gate():
    # TODO(Approver role): swap this interim gate for the dedicated Approver role when it ships.
    if not (current_user.has_full_access or current_user.role == 'accountant'):
        flash('Only an approver (accountant/admin) can approve Delivery Receipts.', 'error')
        return False
    return True


@delivery_receipts_bp.route('/delivery-receipts/<int:id>/approve', methods=['POST'])
@login_required
def approve(id):
    dr = db.get_or_404(DeliveryReceipt, id)
    if dr.branch_id != session.get('selected_branch_id'):
        abort(404)
    if not _approve_role_gate():
        return redirect(url_for('delivery_receipts.view', id=id))
    if dr.status != 'draft':
        flash('Only a draft Delivery Receipt can be approved.', 'error')
        return redirect(url_for('delivery_receipts.view', id=id))
    # Guard: committing these lines must not exceed each SO line's OPEN qty
    # (open excludes THIS dr so a re-check is idempotent).
    for li in dr.line_items:
        open_qty = so_line_open_qty(li.sales_order_item, exclude_dr_id=dr.id)
        if Decimal(str(li.delivered_quantity)) > open_qty:
            prod = li.sales_order_item.product.name if (li.sales_order_item and li.sales_order_item.product) else 'item'
            flash(f'Line {li.line_number}: delivering {li.delivered_quantity} exceeds the open '
                  f'quantity {open_qty} for {prod}.', 'error')
            return redirect(url_for('delivery_receipts.view', id=id))
    dr.status = 'approved'
    dr.approved_by_id = current_user.id
    dr.approved_at = ph_now()
    db.session.commit()
    log_audit(module='delivery_receipts', action='approve', record_id=dr.id,
              record_identifier=dr.dr_number, notes='Approved')
    flash(f'Delivery Receipt "{dr.dr_number}" approved.', 'success')
    return redirect(url_for('delivery_receipts.view', id=id))


@delivery_receipts_bp.route('/delivery-receipts/<int:id>/deliver', methods=['POST'])
@login_required
def mark_delivered(id):
    dr = db.get_or_404(DeliveryReceipt, id)
    if dr.branch_id != session.get('selected_branch_id'):
        abort(404)
    if _dr_role_gate():
        return redirect(url_for('delivery_receipts.view', id=id))
    if dr.status != 'approved':
        flash('Only an approved Delivery Receipt can be marked delivered.', 'error')
        return redirect(url_for('delivery_receipts.view', id=id))
    dr.status = 'delivered'
    dr.delivered_by_id = current_user.id
    dr.delivered_at = ph_now()
    db.session.commit()
    log_audit(module='delivery_receipts', action='update', record_id=dr.id,
              record_identifier=dr.dr_number, notes='Delivered')
    flash(f'Delivery Receipt "{dr.dr_number}" marked delivered.', 'success')
    return redirect(url_for('delivery_receipts.view', id=id))


@delivery_receipts_bp.route('/delivery-receipts/<int:id>/cancel', methods=['POST'])
@login_required
def cancel(id):
    dr = db.get_or_404(DeliveryReceipt, id)
    if dr.branch_id != session.get('selected_branch_id'):
        abort(404)
    if not (current_user.has_full_access or current_user.role == 'accountant'):
        flash('Only accountant/admin can cancel a Delivery Receipt.', 'error')
        return redirect(url_for('delivery_receipts.view', id=id))
    if dr.status == 'billed':
        flash('A billed Delivery Receipt cannot be cancelled.', 'error')
        return redirect(url_for('delivery_receipts.view', id=id))
    reason = (request.form.get('cancel_reason') or '').strip()
    if len(reason) < 10:
        flash('A cancellation reason (min 10 chars) is required.', 'error')
        return redirect(url_for('delivery_receipts.view', id=id))
    dr.status = 'cancelled'
    dr.cancelled_by_id = current_user.id
    dr.cancelled_at = ph_now()
    dr.cancel_reason = reason
    db.session.commit()   # cancelling drops it out of COMMITTED_STATUSES -> qty released
    log_audit(module='delivery_receipts', action='update', record_id=dr.id,
              record_identifier=dr.dr_number, notes=f'Cancelled: {reason}')
    flash(f'Delivery Receipt "{dr.dr_number}" cancelled.', 'warning')
    return redirect(url_for('delivery_receipts.view', id=id))
```

Also add the **edit-lock** to the `edit` route (Task 3): at the top, `if dr.status != 'draft':
flash('Only a draft Delivery Receipt can be edited.', 'error'); return redirect(view)`.

- [ ] **Step 4: Run the lifecycle tests (single-threaded)**

Run: `venv/Scripts/python.exe -m pytest tests/integration/test_delivery_receipts_lifecycle.py -p no:cov -n0 -v`
Expected: PASS (all: guard reject, draft-doesn't-consume, cancel-releases, lock, role gate).

- [ ] **Step 5: Wire the action buttons in `detail.html`**

Add `Approve` / `Mark Delivered` / `Cancel` buttons gated by `dr.status` (custom HTML cancel modal
with `{{ csrf_token() }}` + reason textarea — NO JS popups), mirroring the SO detail's confirm/cancel
modals.

- [ ] **Step 6: Commit**

```bash
git add app/delivery_receipts/views.py app/delivery_receipts/templates/delivery_receipts/detail.html \
        tests/integration/test_delivery_receipts_lifecycle.py
git commit -m "feat(delivery-receipts): approve/deliver/cancel lifecycle + cumulative<=ordered guard at approve"
```

---

### Task 5: Print + SO-detail "Create DR" link + regression-map

**Files:**
- Create: `app/delivery_receipts/templates/delivery_receipts/print.html`
- Modify: `app/delivery_receipts/views.py` (add `print_dr`), `app/sales_orders/templates/sales_orders/detail.html` (Create-DR action), `.claude/regression-map.json`
- Test: `tests/integration/test_delivery_receipts_crud.py` (add print + SO-link tests)

**Interfaces:**
- Consumes: `view`/model (Tasks 1-3).
- Produces: `delivery_receipts.print_dr`.

- [ ] **Step 1: Write the failing test**

Add to `tests/integration/test_delivery_receipts_crud.py`:

```python
def test_print_renders_and_has_no_currency_glyph(client, db_session, admin_user, main_branch):
    so = _confirmed_so(db_session, main_branch.id)
    _login(client, admin_user)
    with client.session_transaction() as s: s['selected_branch_id'] = main_branch.id
    lines = json.dumps([{'sales_order_item_id': so.line_items[0].id, 'delivered_quantity': '3'}])
    client.post('/delivery-receipts/create', data={'sales_order_id': so.id,
        'delivery_date': '2026-07-09', 'lines': lines}, follow_redirects=True)
    dr = DeliveryReceipt.query.filter_by(sales_order_id=so.id).first()
    body = client.get(f'/delivery-receipts/{dr.id}/print').get_data(as_text=True)
    assert dr.dr_number in body and 'Widget' in body
    assert '₱' not in body     # no peso glyph
```

- [ ] **Step 2: Run to verify it fails**

Run: `venv/Scripts/python.exe -m pytest "tests/integration/test_delivery_receipts_crud.py::test_print_renders_and_has_no_currency_glyph" -p no:cov -v`
Expected: FAIL — no `print` route.

- [ ] **Step 3: Add the print route + template**

In `views.py`:

```python
from app.settings import AppSettings


@delivery_receipts_bp.route('/delivery-receipts/<int:id>/print')
@login_required
def print_dr(id):
    dr = db.get_or_404(DeliveryReceipt, id)
    if dr.branch_id != session.get('selected_branch_id'):
        abort(404)
    company = {'name': AppSettings.get_setting('company_name', ''),
               'address': AppSettings.get_setting('company_address', ''),
               'tin': AppSettings.get_setting('company_tin', '')}
    return render_template('delivery_receipts/print.html', dr=dr, company=company,
                           printed_at=ph_now())
```

Create `print.html` — a self-contained delivery document (mirror `sales_orders/print.html` shape):
company header, DR # / date / customer / SO # / salesperson, and a line table
**# · Product · Delivered Qty (`{{ item | qty_fmt }}`) · UOM** (no amounts — it's a delivery doc);
a `window.print()` / `window.close()` bar. No peso glyph.

- [ ] **Step 4: Add the "Create Delivery Receipt" action on the SO detail**

In `app/sales_orders/templates/sales_orders/detail.html`, next to the SO's Print button, add (gated so
it shows only for a confirmed SO when the DR module is on):

```html
{% if so.status == 'confirmed' and module_enabled('delivery_receipts') %}
<a href="{{ url_for('delivery_receipts.create', so=so.id) }}" class="btn btn-secondary">+ Delivery Receipt</a>
{% endif %}
```

(The `create` GET may read `request.args.get('so')` to pre-select that SO in the form — optional
convenience; the picker still lists all eligible SOs.)

- [ ] **Step 5: Map the module in the regression guard**

In `.claude/regression-map.json`, add to `blast_radius`:
`"app/delivery_receipts/models.py": ["delivery_receipts"],`
`"app/delivery_receipts/views.py": ["delivery_receipts"],`
and to `modules`: `"delivery_receipts": { "marker": "delivery_receipts", "e2e": null }`.
Confirm `delivery_receipts` is a registered marker in `pytest.ini` (add it if missing).

- [ ] **Step 6: Run the print test + full DR marker suite**

Run: `venv/Scripts/python.exe -m pytest -m delivery_receipts -p no:cov -n0 -q`
Expected: PASS (all DR tests across the module).

- [ ] **Step 7: Commit**

```bash
git add app/delivery_receipts/templates/delivery_receipts/print.html app/delivery_receipts/views.py \
        app/sales_orders/templates/sales_orders/detail.html .claude/regression-map.json pytest.ini \
        tests/integration/test_delivery_receipts_crud.py
git commit -m "feat(delivery-receipts): printable DR + Create-DR action on the SO detail + regression-map"
```

---

## Post-implementation

- Browser-verify (SO + Products + UoM + delivery_receipts enabled): from a confirmed SO, create a DR
  delivering part of a line → approve (as accountant/admin) → the SO line's open qty drops; a second DR
  can't over-deliver at approve; cancel releases; print renders; nav link gated.
- `pytest.ini`: ensure the `delivery_receipts` marker is registered.
- `/guard cas` before pushing (new blueprint + `module_access.py` + `base.html` are blast-radius).
- Follow-ups (own specs): **DR→SI billing flow** (sub-project #2, sets `billed`+`sales_invoice_id`),
  the **Approver role** (replaces the interim approve gate), R-03 COGS (`post_delivery_je`), the
  pre-printed DR designer, and an SO "fully-delivered" fulfilment status for Order Monitoring.
