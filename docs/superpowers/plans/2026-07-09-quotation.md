# Quotation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Quotation document — a product-priced pre-sale offer with a VAT-treatment mode and a validity period that, when accepted, creates a linked draft Sales Order (front of the Quotation → SO → DR → SI chain).

**Architecture:** A new `app/quotations/` blueprint mirroring `sales_orders`. `Quotation` header + `QuotationItem` lines (line = structural clone of `SalesOrderItem`). A header `vat_treatment` drives a 3-way `calculate_totals`. Accepting a sent, non-expired quote builds a draft `SalesOrder`, translating the quote's VAT treatment into the SO's always-inclusive convention.

**Tech Stack:** Flask + SQLAlchemy + SQLite; Flask-Migrate/Alembic (hand-written batch, `render_as_batch` OFF); pytest (`-p no:cov`, `-n0` for the accept/guard tests).

## Global Constraints

- **`vat_treatment` ∈ {`inclusive`, `exclusive`, `zero_rated`}, default `inclusive`, header-level, Quotation-only.** SO/SI stay VAT-inclusive.
- **`calculate_totals` per treatment:** inclusive → subtotal=Σ amounts, vat extracted, total=subtotal; exclusive → subtotal(net)=Σ amounts, vat=subtotal×12%, total=subtotal+vat; zero_rated → vat=0, total=subtotal=Σ amounts.
- **Lifecycle:** `draft → sent → accepted | rejected | cancelled`. **Lock at sent** (only draft editable). **Derived expiry:** `is_expired = status=='sent' and valid_until < today`; an expired quote **cannot be accepted**.
- **Accept → SO** (sent + not expired only): create a draft `SalesOrder` with `quotation_id`, copy lines translating VAT to inclusive — inclusive: as-is; exclusive: `unit_price ×= 1.12`, `vat_category='V12'`, `vat_rate=12`; zero_rated: `vat_category='V0'`, `vat_rate=0`. Set `quote.status='accepted'`, `quote.sales_order_id=so.id`. Redirect to the SO.
- **Module:** `quotations` — `optional`, `depends_on: ['sales_orders']`, `per_user`, `default_enabled: False`, branch-scoped.
- **Numbering:** `QTN-YYYY-MM-####` per branch/month. **Salesperson** carried via `copy_salesperson` (from `app.sales_orders.models`), Employees-module-gated picker.
- **Standard `Subtotal / VAT / Total` print.** Bare numbers, no peso glyph.
- **OUT OF SCOPE:** revise/clone a sent quote, pre-printed designer, Approver role, any journal entry.
- **⚠️ Migration-fork:** the in-flight Delivery Receipt branch also adds a migration off `main`. Merge one branch first, then reconcile the other's `down_revision` (or `flask db merge`) and verify a SINGLE alembic head before pushing — two heads block all deploys.

---

### Task 1: Models + `SalesOrder.quotation_id` + migration + registration

**Files:**
- Create: `app/quotations/__init__.py` (empty), `app/quotations/models.py`
- Modify: `app/sales_orders/models.py` (add `quotation_id` to `SalesOrder`), `app/__init__.py` (register models)
- Create: `migrations/versions/<generated>_add_quotations.py`
- Test: `tests/unit/test_quotation_model.py`

**Interfaces:**
- Produces: `Quotation` (header, `calculate_totals()`, `is_expired` property), `QuotationItem`
  (`calculate_amounts()`), `generate_quotation_number(branch_id) -> str`. `SalesOrder.quotation_id`.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_quotation_model.py`:

```python
import pytest
from datetime import date, timedelta
from decimal import Decimal
from app.quotations.models import Quotation, QuotationItem

pytestmark = [pytest.mark.integration, pytest.mark.quotations]


def _quote(treatment, amounts):
    q = Quotation(quotation_number='QTN-T', quotation_date=date(2026, 7, 9),
                  valid_until=date(2026, 8, 9), customer_id=1, customer_name='Acme',
                  vat_treatment=treatment, status='draft')
    for i, a in enumerate(amounts, start=1):
        li = QuotationItem(line_number=i, amount=Decimal(str(a)), vat_rate=Decimal('12'))
        li.calculate_amounts()
        q.line_items.append(li)
    q.calculate_totals()
    return q


def test_calculate_totals_three_treatments():
    # inclusive: 1120 gross -> net 1000, vat 120, total 1120
    inc = _quote('inclusive', ['1120.00'])
    assert inc.subtotal == Decimal('1120.00') and inc.vat_amount == Decimal('120.00')
    assert inc.total_amount == Decimal('1120.00')
    # exclusive: 1000 net -> vat 120, total 1120
    exc = _quote('exclusive', ['1000.00'])
    assert exc.subtotal == Decimal('1000.00') and exc.vat_amount == Decimal('120.00')
    assert exc.total_amount == Decimal('1120.00')
    # zero_rated: 1000 -> vat 0, total 1000
    zr = _quote('zero_rated', ['1000.00'])
    assert zr.vat_amount == Decimal('0.00') and zr.total_amount == Decimal('1000.00')


def test_is_expired_only_when_sent_and_past():
    q = _quote('inclusive', ['100.00'])
    q.status = 'sent'; q.valid_until = date.today() - timedelta(days=1)
    assert q.is_expired is True
    q.status = 'draft'
    assert q.is_expired is False           # draft is never "expired"
    q.status = 'sent'; q.valid_until = date.today() + timedelta(days=5)
    assert q.is_expired is False
```

- [ ] **Step 2: Run to verify it fails**

Run: `venv/Scripts/python.exe -m pytest tests/unit/test_quotation_model.py -p no:cov -v`
Expected: FAIL — `No module named 'app.quotations'`.

- [ ] **Step 3: Create the models**

Create `app/quotations/__init__.py` (empty). Create `app/quotations/models.py`:

```python
"""Quotation — a product-priced pre-sale offer. Front of the O2C chain (Quote -> SO -> DR -> SI).
Operational, NOT accounting (posts no JE). vat_treatment is Quotation-only; the SO it creates on
accept is always VAT-inclusive."""
from decimal import Decimal, ROUND_HALF_UP
from app import db
from app.utils import ph_now

VAT_TREATMENTS = ('inclusive', 'exclusive', 'zero_rated')
STANDARD_VAT_RATE = Decimal('12')


class Quotation(db.Model):
    __tablename__ = 'quotations'

    id = db.Column(db.Integer, primary_key=True)
    branch_id = db.Column(db.Integer, db.ForeignKey('branches.id'), nullable=True, index=True)
    branch = db.relationship('Branch', foreign_keys=[branch_id])

    quotation_number = db.Column(db.String(50), unique=True, nullable=False, index=True)
    quotation_date = db.Column(db.Date, nullable=False, index=True)
    valid_until = db.Column(db.Date, nullable=True)

    customer_id = db.Column(db.Integer, db.ForeignKey('customers.id'), nullable=False, index=True)
    customer = db.relationship('Customer')
    customer_name = db.Column(db.String(200), nullable=False)
    customer_tin = db.Column(db.String(20))
    customer_address = db.Column(db.Text)

    payment_terms = db.Column(db.String(50), default='Net 30')
    reference = db.Column(db.String(100))
    notes = db.Column(db.Text, nullable=False, default='')
    vat_treatment = db.Column(db.String(10), default='inclusive', nullable=False)

    status = db.Column(db.String(20), default='draft', nullable=False, index=True)

    salesperson_id = db.Column(db.Integer, db.ForeignKey('employees.id'), nullable=True, index=True)
    salesperson = db.relationship('Employee', foreign_keys=[salesperson_id])
    sales_order_id = db.Column(db.Integer, db.ForeignKey('sales_orders.id'), nullable=True, index=True)

    subtotal = db.Column(db.Numeric(15, 2), default=0.00, nullable=False)
    vat_amount = db.Column(db.Numeric(15, 2), default=0.00, nullable=False)
    total_amount = db.Column(db.Numeric(15, 2), default=0.00, nullable=False)

    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=ph_now, nullable=False)
    updated_at = db.Column(db.DateTime, default=ph_now, onupdate=ph_now, nullable=False)
    sent_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    sent_at = db.Column(db.DateTime)
    accepted_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    accepted_at = db.Column(db.DateTime)
    rejected_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    rejected_at = db.Column(db.DateTime)
    reject_reason = db.Column(db.String(500))
    cancelled_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    cancelled_at = db.Column(db.DateTime)
    cancel_reason = db.Column(db.String(500))

    line_items = db.relationship('QuotationItem', backref='quotation', lazy='select',
                                 cascade='all, delete-orphan', order_by='QuotationItem.line_number')

    @property
    def is_expired(self):
        return (self.status == 'sent' and self.valid_until is not None
                and self.valid_until < ph_now().date())

    def calculate_totals(self):
        gross = sum((Decimal(str(li.amount or 0)) for li in self.line_items), Decimal('0.00'))
        if self.vat_treatment == 'exclusive':
            self.subtotal = gross                                 # net
            self.vat_amount = (gross * STANDARD_VAT_RATE / 100).quantize(Decimal('0.01'), ROUND_HALF_UP)
            self.total_amount = self.subtotal + self.vat_amount
        elif self.vat_treatment == 'zero_rated':
            self.subtotal = gross
            self.vat_amount = Decimal('0.00')
            self.total_amount = gross
        else:  # inclusive
            self.subtotal = gross
            self.vat_amount = sum((Decimal(str(li.vat_amount or 0)) for li in self.line_items),
                                  Decimal('0.00'))
            self.total_amount = gross

    def to_dict(self):
        return {
            'id': self.id, 'quotation_number': self.quotation_number, 'status': self.status,
            'vat_treatment': self.vat_treatment, 'is_expired': self.is_expired,
            'valid_until': self.valid_until.isoformat() if self.valid_until else None,
            'customer_name': self.customer_name,
            'salesperson_id': self.salesperson_id,
            'salesperson_name': self.salesperson.full_name if self.salesperson else None,
            'sales_order_id': self.sales_order_id,
            'sales_order_number': self.sales_order.so_number if self.sales_order_id and getattr(self, 'sales_order', None) else None,
            'total_amount': float(self.total_amount) if self.total_amount is not None else 0.0,
        }


class QuotationItem(db.Model):
    __tablename__ = 'quotation_items'

    id = db.Column(db.Integer, primary_key=True)
    quotation_id = db.Column(db.Integer, db.ForeignKey('quotations.id'), nullable=False, index=True)
    line_number = db.Column(db.Integer, nullable=False)
    amount = db.Column(db.Numeric(15, 2), default=0.00, nullable=False)
    quantity = db.Column(db.Numeric(15, 4), nullable=True)
    unit_price = db.Column(db.Numeric(15, 2), nullable=True)
    uom_text = db.Column(db.String(20), nullable=True)
    unit_of_measure_id = db.Column(db.Integer, db.ForeignKey('units_of_measure.id'), nullable=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=True)
    unit_of_measure = db.relationship('UnitOfMeasure')
    product = db.relationship('Product')
    vat_category = db.Column(db.String(100))
    vat_rate = db.Column(db.Numeric(5, 2), default=0.00, nullable=False)
    line_total = db.Column(db.Numeric(15, 2), default=0.00, nullable=False)
    vat_amount = db.Column(db.Numeric(15, 2), default=0.00, nullable=False)

    def calculate_amounts(self):
        """Amount = qty × unit_price when both set; extract line VAT (inclusive) for the
        inclusive-treatment summary. Mirror SalesOrderItem."""
        if self.quantity is not None and self.unit_price is not None:
            q = Decimal(str(self.quantity)); up = Decimal(str(self.unit_price))
            if q > 0 and up > 0:
                self.amount = (q * up).quantize(Decimal('0.01'), ROUND_HALF_UP)
        amt = Decimal(str(self.amount or 0))
        rate = Decimal(str(self.vat_rate or 0))
        if rate > 0:
            net = (amt / (1 + rate / 100)).quantize(Decimal('0.01'), ROUND_HALF_UP)
            self.vat_amount = amt - net
        else:
            self.vat_amount = Decimal('0.00')
        self.line_total = amt

    def to_dict(self):
        return {
            'id': self.id, 'line_number': self.line_number,
            'amount': float(self.amount) if self.amount is not None else 0.0,
            'quantity': float(self.quantity) if self.quantity is not None else None,
            'unit_price': float(self.unit_price) if self.unit_price is not None else None,
            'uom_display': (self.unit_of_measure.code if self.unit_of_measure else self.uom_text),
            'product_id': self.product_id,
            'product_code': self.product.code if self.product else None,
            'product_name': self.product.name if self.product else None,
            'vat_category': self.vat_category,
            'vat_rate': float(self.vat_rate) if self.vat_rate is not None else 0.0,
        }


def generate_quotation_number(branch_id):
    """Next QTN-YYYY-MM-#### for the current PH month (mirror generate_so_number)."""
    today = ph_now().date()
    prefix = f"QTN-{today.year:04d}-{today.month:02d}-"
    rows = (Quotation.query.filter(Quotation.quotation_number.like(prefix + '%'))
            .with_entities(Quotation.quotation_number).all())
    nums = []
    for (n,) in rows:
        tail = n.rsplit('-', 1)[-1]
        if tail.isdigit():
            nums.append(int(tail))
    return f"{prefix}{(max(nums) + 1) if nums else 1:04d}"
```

- [ ] **Step 4: Add the `sales_order` relationship + `SalesOrder.quotation_id`**

In `app/quotations/models.py` `Quotation`, add the reverse relationship (place after the `sales_order_id` column):

```python
    sales_order = db.relationship('SalesOrder', foreign_keys=[sales_order_id])
```

In `app/sales_orders/models.py`, in `SalesOrder`, add:

```python
    quotation_id = db.Column(db.Integer, db.ForeignKey('quotations.id'), nullable=True, index=True)
```

- [ ] **Step 5: Register the models in `create_app`**

In `app/__init__.py`, next to the sales-orders model import, add:

```python
    from app.quotations.models import Quotation, QuotationItem
```

- [ ] **Step 6: Run the model test**

Run: `venv/Scripts/python.exe -m pytest tests/unit/test_quotation_model.py -p no:cov -v`
Expected: PASS.

- [ ] **Step 7: Scaffold + write the migration**

Run: `venv/Scripts/python.exe -m flask db revision -m "add quotations and quotation_id on sales_orders"`

Body: create `quotations` (all columns above) + `quotation_items` via `op.create_table` (mirror the
Task-1 DR migration shape; include the `vat_treatment` String(10) NOT NULL server_default `'inclusive'`
column and the money/audit columns), the indexes, and:

```python
    with op.batch_alter_table('sales_orders', schema=None) as b:
        b.add_column(sa.Column('quotation_id', sa.Integer(), sa.ForeignKey('quotations.id'), nullable=True))
        b.create_index('ix_sales_orders_quotation_id', ['quotation_id'])
```
`downgrade`: drop `sales_orders.quotation_id` (+ index), then `quotation_items`, then `quotations`.

- [ ] **Step 8: Verify on a copy of cas.db, then apply**

```bash
cp instance/cas.db instance/_x.db
SQLALCHEMY_DATABASE_URI=sqlite:///_x.db venv/Scripts/python.exe -m flask db upgrade
venv/Scripts/python.exe -c "import sqlite3; c=sqlite3.connect('instance/_x.db'); \
t=[r[0] for r in c.execute(\"SELECT name FROM sqlite_master WHERE type='table'\")]; \
cols=[r[1] for r in c.execute('PRAGMA table_info(sales_orders)')]; \
print('quotations' in t, 'quotation_items' in t, 'quotation_id' in cols)"
rm -f instance/_x.db
venv/Scripts/python.exe -m flask db upgrade
```

Expected: prints `True True True`; demo DB upgrade clean.

- [ ] **Step 9: Commit**

```bash
git add app/quotations/__init__.py app/quotations/models.py app/sales_orders/models.py app/__init__.py \
        migrations/versions/*add_quotations*.py tests/unit/test_quotation_model.py
git commit -m "feat(quotations): Quotation + item models (3-way vat_treatment, is_expired), SO.quotation_id, migration"
```

---

### Task 2: Module registry + blueprint + nav

**Files:**
- Create: `app/quotations/views.py` (blueprint + stub `list`), `app/quotations/templates/quotations/list.html`
- Modify: `app/users/module_access.py`, `app/__init__.py`, `app/templates/base.html`
- Test: `tests/integration/test_quotations_gate.py`

**Interfaces:** Produces `quotations_bp`, `quotations.list`, the `quotations` module gate.

- [ ] **Step 1: Write the failing test** — mirror `tests/integration/test_delivery_receipts_gate.py` (from
  the DR plan) exactly, swapping `delivery_receipts`→`quotations`, route `/quotations`, and the
  registry assertion `depends_on == ['sales_orders']`.

- [ ] **Step 2: Run to verify it fails.** `venv/Scripts/python.exe -m pytest tests/integration/test_quotations_gate.py -p no:cov -v` → FAIL (no route/registry).

- [ ] **Step 3: Create the blueprint + stub list** — mirror the DR Task-2 `views.py`/`list.html`,
  `quotations_bp = Blueprint('quotations', ...)`, `VALID_QUOTATION_STATUSES = {'draft','sent',
  'accepted','rejected','cancelled'}`, a branch-scoped `list` route + `list.html` (columns QTN # ·
  Date · Customer · Valid Until · Status, showing "Expired" when `q.is_expired`).

- [ ] **Step 4: Registry entry** — in `app/users/module_access.py`, after the `delivery_receipts` (or
  `sales_orders`) entry:

```python
    {'key': 'quotations', 'label': 'Quotations', 'section': 'Transactions',
     'area': 'Sales', 'group': 'Documents',
     'optional': True, 'depends_on': ['sales_orders'], 'default_enabled': False, 'per_user': True,
     'endpoints': ('quotations.',)},
```

- [ ] **Step 5: Register the blueprint** — `from app.quotations.views import quotations_bp` +
  `app.register_blueprint(quotations_bp)` in `create_app`.

- [ ] **Step 6: Nav** — add `quotations` to the base.html routes/icons dicts:
  `'quotations': 'quotations.list',` and `'quotations': '📝',`.

- [ ] **Step 7: Run the gate test** → PASS.

- [ ] **Step 8: Commit**

```bash
git add app/quotations/views.py app/quotations/templates/ app/users/module_access.py \
        app/__init__.py app/templates/base.html tests/integration/test_quotations_gate.py
git commit -m "feat(quotations): optional module (depends_on sales_orders) + blueprint + nav + list"
```

---

### Task 3: Create / view / edit a draft Quotation

**Files:**
- Create: `app/quotations/forms.py`, templates `form.html`, `detail.html`
- Modify: `app/quotations/views.py` (add `create`, `view`, `edit` + helpers)
- Test: `tests/integration/test_quotations_crud.py`

**Interfaces:** Consumes `generate_quotation_number` (Task 1), `copy_salesperson`
(`app.sales_orders.models`). Produces `quotations.create`, `.view`, `.edit`.

- [ ] **Step 1: Write the failing test** — an autouse `quotations` + `sales_orders` enable fixture;
  create a draft quote (customer + one product line + `vat_treatment='exclusive'` + `valid_until`),
  POST `/quotations/create`, assert it persists as `draft`, snapshots the customer, carries the line,
  and `vat_treatment == 'exclusive'`.

```python
def test_create_draft_quote_persists(client, db_session, admin_user, main_branch):
    from app.quotations.models import Quotation
    c = _customer(db_session); p = _product(db_session)
    _login(client, admin_user)
    with client.session_transaction() as s: s['selected_branch_id'] = main_branch.id
    lines = json.dumps([{'product_id': str(p.id), 'quantity': '2', 'unit_price': '100.00',
                         'vat_category': 'V12', 'vat_rate': '12'}])
    client.post('/quotations/create', data={'customer_id': str(c.id),
        'quotation_date': '2026-07-09', 'valid_until': '2026-08-09',
        'vat_treatment': 'exclusive', 'payment_terms': 'Net 30', 'lines': lines},
        follow_redirects=True)
    q = Quotation.query.filter_by(customer_id=c.id).first()
    assert q is not None and q.status == 'draft' and q.vat_treatment == 'exclusive'
    assert q.customer_name and q.line_items[0].quantity == Decimal('2')
```

- [ ] **Step 2: Run to verify it fails** → FAIL (no create route).

- [ ] **Step 3: Add the form** — `app/quotations/forms.py`, `QuotationForm` mirroring
  `SalesInvoiceForm`/`SalesOrderForm` header fields, plus:

```python
    vat_treatment = SelectField('VAT Treatment', choices=[
        ('inclusive', 'VAT-Inclusive'), ('exclusive', 'VAT-Exclusive'),
        ('zero_rated', 'Zero-Rated')], default='inclusive')
    valid_until = DateField('Valid Until', validators=[Optional()], format='%Y-%m-%d')
```

- [ ] **Step 4: Add create/view/edit + line parser** — mirror the SO create/edit (product line grid,
  hidden `lines` JSON → `QuotationItem`s with `calculate_amounts()`, `copy_salesperson`, then
  `q.calculate_totals()`). `edit` is draft-only (`if q.status != 'draft': flash+redirect`). Product
  line parsing mirrors `sales_orders.views._parse_and_attach_so_lines` (but no product-required guard —
  a quote may itemize freely). `create` sets `quotation_number = generate_quotation_number(branch_id)`.

- [ ] **Step 5: Create `form.html` + `detail.html`** — `form.html` = customer picker + `vat_treatment`
  select + `valid_until` + the SO-style product line grid. `detail.html` = header (QTN #, dates, valid-until,
  customer, salesperson, VAT treatment, status badge + "Expired" when `is_expired`) + line table + the
  **Subtotal / VAT / Total** summary + status-gated action buttons (Send / Accept / Reject / Cancel —
  Task 4, custom HTML modals, no JS popups). Bare numbers; no peso glyph.

- [ ] **Step 6: Run the create test** → PASS.

- [ ] **Step 7: Commit**

```bash
git add app/quotations/forms.py app/quotations/views.py app/quotations/templates/ \
        tests/integration/test_quotations_crud.py
git commit -m "feat(quotations): create/view/edit draft quote (vat_treatment, product lines, salesperson)"
```

---

### Task 4: Lifecycle (send/reject/cancel + lock) + accept → SO (the core)

**Files:**
- Modify: `app/quotations/views.py` (add `send`, `accept`, `reject`, `cancel`; edit-lock), `detail.html` (buttons)
- Test: `tests/integration/test_quotations_lifecycle.py`

**Interfaces:** Consumes the draft-create flow (Task 3), `SalesOrder`/`SalesOrderItem`/`copy_salesperson`.
Produces `quotations.send`, `.accept`, `.reject`, `.cancel`.

- [ ] **Step 1: Write the failing tests** — cover: `send` (draft→sent, locks: GET `/edit` on a sent
  quote redirects); a sent quote past `valid_until` → `is_expired` and **accept refused** (stays sent,
  flash "expired"); `reject`/`cancel` need a reason; and the accept-translation core:

```python
def test_accept_creates_linked_inclusive_so_from_exclusive_quote(client, db_session, admin_user, main_branch):
    from app.quotations.models import Quotation
    from app.sales_orders.models import SalesOrder
    from decimal import Decimal
    c = _customer(db_session); p = _product(db_session)
    _login(client, admin_user)
    with client.session_transaction() as s: s['selected_branch_id'] = main_branch.id
    lines = json.dumps([{'product_id': str(p.id), 'quantity': '2', 'unit_price': '100.00',
                         'vat_category': 'V12', 'vat_rate': '12'}])
    client.post('/quotations/create', data={'customer_id': str(c.id), 'quotation_date': '2026-07-09',
        'valid_until': '2026-08-09', 'vat_treatment': 'exclusive', 'payment_terms': 'Net 30',
        'lines': lines}, follow_redirects=True)
    q = Quotation.query.filter_by(customer_id=c.id).first()
    client.post(f'/quotations/{q.id}/send', follow_redirects=True)
    client.post(f'/quotations/{q.id}/accept', follow_redirects=True)
    db_session.refresh(q)
    assert q.status == 'accepted' and q.sales_order_id is not None
    so = db_session.get(SalesOrder, q.sales_order_id)
    assert so.status == 'draft' and so.quotation_id == q.id
    # exclusive net 100 -> SO inclusive unit_price 112 (VAT folded in)
    assert so.line_items[0].unit_price == Decimal('112.00')
    assert so.line_items[0].vat_category == 'V12'
```

- [ ] **Step 2: Run to verify it fails** — `-n0` → FAIL (no accept route).

- [ ] **Step 3: Implement the transitions** — add to `views.py` (`ph_now`, `log_audit` imported):

```python
def _quote_admin_gate():
    if not (current_user.has_full_access or current_user.role == 'accountant'):
        flash('Only accountant/admin can perform this action.', 'error')
        return False
    return True


@quotations_bp.route('/quotations/<int:id>/send', methods=['POST'])
@login_required
def send(id):
    q = db.get_or_404(Quotation, id)
    if q.branch_id != session.get('selected_branch_id'):
        abort(404)
    if q.status != 'draft':
        flash('Only a draft quotation can be sent.', 'error')
        return redirect(url_for('quotations.view', id=id))
    q.status = 'sent'; q.sent_by_id = current_user.id; q.sent_at = ph_now()
    db.session.commit()
    log_audit(module='quotations', action='update', record_id=q.id,
              record_identifier=q.quotation_number, notes='Sent')
    flash(f'Quotation "{q.quotation_number}" sent.', 'success')
    return redirect(url_for('quotations.view', id=id))


@quotations_bp.route('/quotations/<int:id>/accept', methods=['POST'])
@login_required
def accept(id):
    q = db.get_or_404(Quotation, id)
    if q.branch_id != session.get('selected_branch_id'):
        abort(404)
    if not _quote_admin_gate():
        return redirect(url_for('quotations.view', id=id))
    if q.status != 'sent':
        flash('Only a sent quotation can be accepted.', 'error')
        return redirect(url_for('quotations.view', id=id))
    if q.is_expired:
        flash('This quotation has expired and can no longer be accepted.', 'error')
        return redirect(url_for('quotations.view', id=id))
    from app.sales_orders.models import SalesOrder, SalesOrderItem, copy_salesperson
    from app.sales_orders.views import generate_so_number
    from decimal import Decimal, ROUND_HALF_UP
    try:
        so = SalesOrder(so_number=generate_so_number(q.branch_id), branch_id=q.branch_id,
                        order_date=ph_now().date(), customer_id=q.customer_id,
                        customer_name=q.customer_name, customer_tin=q.customer_tin,
                        customer_address=q.customer_address, payment_terms=q.payment_terms,
                        reference=q.reference, notes=q.notes or '', status='draft',
                        quotation_id=q.id, created_by_id=current_user.id)
        copy_salesperson(q, so)
        for qi in q.line_items:
            up = qi.unit_price
            vat_cat, vat_rate = qi.vat_category, qi.vat_rate
            if q.vat_treatment == 'exclusive' and up is not None:
                up = (Decimal(str(up)) * Decimal('1.12')).quantize(Decimal('0.01'), ROUND_HALF_UP)
                vat_cat, vat_rate = 'V12', Decimal('12')
            elif q.vat_treatment == 'zero_rated':
                vat_cat, vat_rate = 'V0', Decimal('0')
            si = SalesOrderItem(line_number=qi.line_number, product_id=qi.product_id,
                                quantity=qi.quantity, unit_price=up, uom_text=qi.uom_text,
                                unit_of_measure_id=qi.unit_of_measure_id,
                                amount=(Decimal(str(up)) * Decimal(str(qi.quantity))
                                        ).quantize(Decimal('0.01'), ROUND_HALF_UP)
                                        if (up is not None and qi.quantity is not None) else qi.amount,
                                vat_category=vat_cat, vat_rate=vat_rate)
            si.calculate_amounts()
            so.line_items.append(si)
        so.calculate_totals()
        db.session.add(so); db.session.flush()
        q.status = 'accepted'; q.accepted_by_id = current_user.id; q.accepted_at = ph_now()
        q.sales_order_id = so.id
        db.session.commit()
        log_audit(module='quotations', action='accept', record_id=q.id,
                  record_identifier=q.quotation_number, notes=f'Accepted -> {so.so_number}')
        flash(f'Quotation accepted. Sales Order "{so.so_number}" created (draft).', 'success')
        return redirect(url_for('sales_orders.view', id=so.id))
    except Exception:
        db.session.rollback()
        flash('An error occurred creating the Sales Order from this quotation.', 'error')
        return redirect(url_for('quotations.view', id=id))


@quotations_bp.route('/quotations/<int:id>/reject', methods=['POST'])
@login_required
def reject(id):
    q = db.get_or_404(Quotation, id)
    if q.branch_id != session.get('selected_branch_id'):
        abort(404)
    if not _quote_admin_gate():
        return redirect(url_for('quotations.view', id=id))
    if q.status != 'sent':
        flash('Only a sent quotation can be rejected.', 'error')
        return redirect(url_for('quotations.view', id=id))
    reason = (request.form.get('reject_reason') or '').strip()
    if len(reason) < 10:
        flash('A rejection reason (min 10 chars) is required.', 'error')
        return redirect(url_for('quotations.view', id=id))
    q.status = 'rejected'; q.rejected_by_id = current_user.id; q.rejected_at = ph_now()
    q.reject_reason = reason
    db.session.commit()
    log_audit(module='quotations', action='update', record_id=q.id,
              record_identifier=q.quotation_number, notes=f'Rejected: {reason}')
    flash(f'Quotation "{q.quotation_number}" rejected.', 'warning')
    return redirect(url_for('quotations.view', id=id))


@quotations_bp.route('/quotations/<int:id>/cancel', methods=['POST'])
@login_required
def cancel(id):
    q = db.get_or_404(Quotation, id)
    if q.branch_id != session.get('selected_branch_id'):
        abort(404)
    if not _quote_admin_gate():
        return redirect(url_for('quotations.view', id=id))
    if q.status in ('accepted', 'cancelled'):
        flash('This quotation can no longer be cancelled.', 'error')
        return redirect(url_for('quotations.view', id=id))
    reason = (request.form.get('cancel_reason') or '').strip()
    if len(reason) < 10:
        flash('A cancellation reason (min 10 chars) is required.', 'error')
        return redirect(url_for('quotations.view', id=id))
    q.status = 'cancelled'; q.cancelled_by_id = current_user.id; q.cancelled_at = ph_now()
    q.cancel_reason = reason
    db.session.commit()
    log_audit(module='quotations', action='update', record_id=q.id,
              record_identifier=q.quotation_number, notes=f'Cancelled: {reason}')
    flash(f'Quotation "{q.quotation_number}" cancelled.', 'warning')
    return redirect(url_for('quotations.view', id=id))
```

Add `log_audit` + `ph_now` to the `views.py` imports.

- [ ] **Step 4: Run the lifecycle tests (single-threaded)**

Run: `venv/Scripts/python.exe -m pytest tests/integration/test_quotations_lifecycle.py -p no:cov -n0 -v`
Expected: PASS (send/lock, expired-can't-accept, reject/cancel reason, accept→SO with exclusive/
zero-rated/inclusive translation + link + salesperson).

- [ ] **Step 5: Wire the detail action buttons** — Send / Accept / Reject / Cancel gated by `q.status`
  and `q.is_expired` (custom HTML modals w/ `{{ csrf_token() }}` + reason textareas; no JS popups).

- [ ] **Step 6: Commit**

```bash
git add app/quotations/views.py app/quotations/templates/quotations/detail.html \
        tests/integration/test_quotations_lifecycle.py
git commit -m "feat(quotations): send/reject/cancel + accept->create linked draft SO (vat_treatment translation)"
```

---

### Task 5: Print + regression-map + migration-fork note

**Files:**
- Create: `app/quotations/templates/quotations/print.html`
- Modify: `app/quotations/views.py` (add `print_quote`), `.claude/regression-map.json`, `pytest.ini`
- Test: `tests/integration/test_quotations_crud.py` (add print test)

**Interfaces:** Produces `quotations.print_quote`.

- [ ] **Step 1: Write the failing test** — create a quote, GET `/quotations/<id>/print`, assert the
  QTN #, the product name, the treatment label, and Subtotal/VAT/Total appear, and **no `₱`**.

- [ ] **Step 2: Run to verify it fails** → FAIL (no print route).

- [ ] **Step 3: Add the print route + template** — `print_quote(id)` (mirror the SO print route:
  company from AppSettings + `render_template('quotations/print.html', ...)`). `print.html` = a
  self-contained quotation: company header, QTN # / dates / valid-until / customer / salesperson /
  **VAT treatment label**, line table (# · Product · Qty `{{ item | qty_fmt }}` · UOM · Unit Price ·
  Amount), and the **Subtotal / VAT / Total** summary. `window.print()`/`window.close()` bar. No peso glyph.

- [ ] **Step 4: Regression-map + marker** — add to `.claude/regression-map.json` blast_radius
  `"app/quotations/models.py": ["quotations"]`, `"app/quotations/views.py": ["quotations"]`, and to
  modules `"quotations": { "marker": "quotations", "e2e": null }`. Ensure `quotations` is a registered
  marker in `pytest.ini`.

- [ ] **Step 5: Run the print test + full quotations marker suite**

Run: `venv/Scripts/python.exe -m pytest -m quotations -p no:cov -n0 -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/quotations/templates/quotations/print.html app/quotations/views.py \
        .claude/regression-map.json pytest.ini tests/integration/test_quotations_crud.py
git commit -m "feat(quotations): printable quotation (treatment-aware summary) + regression-map"
```

---

## Post-implementation

- Browser-verify (SO + Products + UoM + quotations enabled): create a quote in each `vat_treatment`
  (inclusive/exclusive/zero-rated) → the summary math matches; send → accept → a linked draft SO appears
  (VAT-inclusive, exclusive-folded / zero-rated-tagged); an expired sent quote can't be accepted; print
  renders per treatment; nav gated.
- **⚠️ Before merging/pushing: reconcile the alembic heads with the Delivery Receipt branch.** Both add
  a migration off the same `main`. After both merge, run `flask db heads` — if TWO, add a `flask db
  merge` (or rebase one's `down_revision`) and verify a SINGLE head on a copy of `cas.db` before push.
  Two heads block ALL client deploys.
- `pytest.ini`: ensure the `quotations` marker is registered.
- `/guard cas` before pushing (new blueprint + `module_access.py` + `base.html` + `sales_orders/models.py`
  are blast-radius).
- Follow-ups (own specs): revise/clone a sent quote, pre-printed quotation designer, the Approver role
  (which would gate send/accept), and quote-win reporting.
