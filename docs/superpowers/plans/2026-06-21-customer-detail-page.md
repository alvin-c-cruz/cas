# Customer Detail Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give Customers a detail page (`/customers/<id>`) that mirrors the Vendor detail page — Overview tab (Customer Info + AR Aging + Creditable WHT YTD) and Invoices tab (filterable, paginated).

**Architecture:** A new `customers.detail` view mirrors `vendors.detail` exactly; two new aging/WHT helpers go in a new `app/customers/utils.py` mirroring `app/vendors/utils.py`; a new `customers/detail.html` mirrors `vendors/detail.html`; the customer-list code/name links re-point from `customers.edit` to the new detail page. No model changes, no migration.

**Tech Stack:** Flask, SQLAlchemy, Jinja2, pytest. Spec: `docs/superpowers/specs/2026-06-21-customer-detail-page-design.md`.

## Global Constraints

- Use the literal `₱` (U+20B1) glyph, never `&#8369;`.
- No JavaScript popups (none needed here).
- No hardcoded styling outside the template's own scoped `<style>` block (mirrors how `vendors/detail.html` scopes its styles); use design-token CSS vars (`var(--text-2)`, `var(--red)`, `var(--blue)`, `var(--border)`).
- TDD: write the failing test first, watch it fail, implement, watch it pass, commit.
- Auto-commit each task to `main` (no push). Commit message trailer: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.
- `customers.detail` is a **read** view: `@login_required` only, no inline role gate, no `log_audit` call (matches `vendors.detail`). Staff access is already governed by the `'customers.'` prefix in `app/users/module_access.py` — no registry change.
- Reference fields verified against source: `SalesInvoice` (`invoice_number`, `invoice_date`, `due_date`, `customer_id`, `subtotal`, `vat_amount`, `withholding_tax_amount`, `total_amount`, `status`, `balance`); `SalesInvoiceItem` (`invoice_id`, `wt_id`, `wt_amount`); `Customer` has **no** `check_payee_name`.

---

### Task 1: AR aging + creditable-WHT helpers (`app/customers/utils.py`)

**Files:**
- Create: `app/customers/utils.py`
- Test: `tests/unit/test_customer_utils.py`

**Interfaces:**
- Consumes: `SalesInvoice`, `SalesInvoiceItem` (`app/sales_invoices/models.py`); `WithholdingTax` (`app/withholding_tax/models.py`); `ph_now` (`app/utils`).
- Produces:
  - `compute_ar_aging(customer_id) -> dict` with keys `current`, `1_30`, `31_60`, `61_90`, `90_plus`, `total` (all `Decimal`).
  - `compute_creditable_wht_ytd(customer_id) -> list[dict]` of `{'code': str, 'name': str, 'total': Decimal}`.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_customer_utils.py`:

```python
"""Unit tests for customer AR-aging and creditable-WHT helpers."""
from datetime import timedelta
from decimal import Decimal

import pytest

from app.utils import ph_now
from app.customers.models import Customer
from app.sales_invoices.models import SalesInvoice, SalesInvoiceItem
from app.withholding_tax.models import WithholdingTax
from app.customers.utils import compute_ar_aging, compute_creditable_wht_ytd


def _customer(db_session, code='C001'):
    c = Customer(code=code, name=f'Customer {code}', is_active=True)
    db_session.add(c)
    db_session.commit()
    return c


def _invoice(db_session, customer, number, days_to_due, status='posted',
             balance='1000.00'):
    """Create an SI whose due_date is `days_to_due` from today (negative = overdue)."""
    due = ph_now().date() + timedelta(days=days_to_due)
    inv = SalesInvoice(
        invoice_number=number,
        invoice_date=ph_now().date(),
        due_date=due,
        customer_id=customer.id,
        customer_name=customer.name,
        status=status,
        balance=Decimal(balance),
    )
    db_session.add(inv)
    db_session.commit()
    return inv


@pytest.mark.unit
def test_ar_aging_buckets_by_days_overdue(db_session):
    c = _customer(db_session)
    _invoice(db_session, c, 'SI-1', days_to_due=10, balance='100.00')    # current
    _invoice(db_session, c, 'SI-2', days_to_due=-15, balance='200.00')   # 1-30
    _invoice(db_session, c, 'SI-3', days_to_due=-45, balance='300.00')   # 31-60
    _invoice(db_session, c, 'SI-4', days_to_due=-75, balance='400.00')   # 61-90
    _invoice(db_session, c, 'SI-5', days_to_due=-120, balance='500.00')  # 90+

    aging = compute_ar_aging(c.id)

    assert aging['current'] == Decimal('100.00')
    assert aging['1_30'] == Decimal('200.00')
    assert aging['31_60'] == Decimal('300.00')
    assert aging['61_90'] == Decimal('400.00')
    assert aging['90_plus'] == Decimal('500.00')
    assert aging['total'] == Decimal('1500.00')


@pytest.mark.unit
def test_ar_aging_excludes_draft_and_paid(db_session):
    c = _customer(db_session)
    _invoice(db_session, c, 'SI-1', days_to_due=10, status='posted', balance='100.00')
    _invoice(db_session, c, 'SI-2', days_to_due=10, status='draft', balance='999.00')
    _invoice(db_session, c, 'SI-3', days_to_due=10, status='paid', balance='888.00')
    _invoice(db_session, c, 'SI-4', days_to_due=-5, status='partially_paid', balance='50.00')

    aging = compute_ar_aging(c.id)

    assert aging['current'] == Decimal('100.00')   # only the posted one
    assert aging['1_30'] == Decimal('50.00')       # partially_paid counts
    assert aging['total'] == Decimal('150.00')


@pytest.mark.unit
def test_ar_aging_skips_null_due_date(db_session):
    c = _customer(db_session)
    inv = _invoice(db_session, c, 'SI-1', days_to_due=10, balance='100.00')
    inv.due_date = None
    db_session.commit()

    aging = compute_ar_aging(c.id)

    assert aging['total'] == Decimal('0.00')


@pytest.mark.unit
def test_creditable_wht_ytd_groups_by_code(db_session):
    c = _customer(db_session)
    wt = WithholdingTax(code='WC010', name='Professional 10%', rate=Decimal('10.00'),
                        is_active=True)
    db_session.add(wt)
    db_session.commit()

    inv = _invoice(db_session, c, 'SI-1', days_to_due=10, status='posted')
    db_session.add(SalesInvoiceItem(invoice_id=inv.id, line_number=1,
                                    description='Service A', wt_id=wt.id,
                                    wt_amount=Decimal('30.00')))
    db_session.add(SalesInvoiceItem(invoice_id=inv.id, line_number=2,
                                    description='Service B', wt_id=wt.id,
                                    wt_amount=Decimal('20.00')))
    db_session.commit()

    rows = compute_creditable_wht_ytd(c.id)

    assert len(rows) == 1
    assert rows[0]['code'] == 'WC010'
    assert rows[0]['total'] == Decimal('50.00')


@pytest.mark.unit
def test_creditable_wht_ytd_posted_only_and_null_wt_excluded(db_session):
    c = _customer(db_session)
    wt = WithholdingTax(code='WC010', name='Professional 10%', rate=Decimal('10.00'),
                        is_active=True)
    db_session.add(wt)
    db_session.commit()

    posted = _invoice(db_session, c, 'SI-1', days_to_due=10, status='posted')
    draft = _invoice(db_session, c, 'SI-2', days_to_due=10, status='draft')
    db_session.add(SalesInvoiceItem(invoice_id=posted.id, line_number=1,
                                    description='Billed', wt_id=wt.id,
                                    wt_amount=Decimal('30.00')))
    db_session.add(SalesInvoiceItem(invoice_id=posted.id, line_number=2,
                                    description='No WHT line', wt_id=None,
                                    wt_amount=Decimal('0.00')))
    db_session.add(SalesInvoiceItem(invoice_id=draft.id, line_number=1,
                                    description='Draft line', wt_id=wt.id,
                                    wt_amount=Decimal('99.00')))
    db_session.commit()

    rows = compute_creditable_wht_ytd(c.id)

    assert len(rows) == 1
    assert rows[0]['total'] == Decimal('30.00')   # draft + null-wt excluded
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/unit/test_customer_utils.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.customers.utils'` (or ImportError on the two functions).

- [ ] **Step 3: Write the implementation**

Create `app/customers/utils.py`:

```python
from decimal import Decimal
from app.utils import ph_now


def compute_ar_aging(customer_id):
    """Return AR aging buckets for a customer (posted and partially-paid invoices)."""
    from app.sales_invoices.models import SalesInvoice
    today = ph_now().date()
    invoices = SalesInvoice.query.filter(
        SalesInvoice.customer_id == customer_id,
        SalesInvoice.status.in_(['posted', 'partially_paid'])
    ).all()
    buckets = {
        'current': Decimal('0.00'),
        '1_30': Decimal('0.00'),
        '31_60': Decimal('0.00'),
        '61_90': Decimal('0.00'),
        '90_plus': Decimal('0.00'),
    }
    for inv in invoices:
        if inv.due_date is None:
            continue
        days_overdue = (today - inv.due_date).days
        amount = inv.balance or Decimal('0.00')
        if days_overdue <= 0:
            buckets['current'] += amount
        elif days_overdue <= 30:
            buckets['1_30'] += amount
        elif days_overdue <= 60:
            buckets['31_60'] += amount
        elif days_overdue <= 90:
            buckets['61_90'] += amount
        else:
            buckets['90_plus'] += amount
    buckets['total'] = sum(buckets.values(), Decimal('0.00'))
    return buckets


def compute_creditable_wht_ytd(customer_id):
    """Return list of {code, name, total} for creditable WHT (BIR 2307) the customer
    withheld from us this calendar year. Mirrors vendors.compute_wht_ytd; the math is
    identical, only the AR-side meaning differs."""
    from app import db
    from app.sales_invoices.models import SalesInvoice, SalesInvoiceItem
    from app.withholding_tax.models import WithholdingTax
    from sqlalchemy import extract
    year = ph_now().year
    rows = (
        db.session.query(
            SalesInvoiceItem.wt_id,
            db.func.sum(SalesInvoiceItem.wt_amount).label('total')
        )
        .join(SalesInvoice, SalesInvoiceItem.invoice_id == SalesInvoice.id)
        .filter(
            SalesInvoice.customer_id == customer_id,
            SalesInvoice.status == 'posted',
            extract('year', SalesInvoice.invoice_date) == year,
            SalesInvoiceItem.wt_id.isnot(None),
        )
        .group_by(SalesInvoiceItem.wt_id)
        .all()
    )
    wt_ids = [row.wt_id for row in rows]
    wt_map = {wt.id: wt for wt in WithholdingTax.query.filter(WithholdingTax.id.in_(wt_ids)).all()}
    result = []
    for row in rows:
        wt = wt_map.get(row.wt_id)
        if wt:
            result.append({'code': wt.code, 'name': wt.name, 'total': row.total or Decimal('0.00')})
    return result
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/unit/test_customer_utils.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add app/customers/utils.py tests/unit/test_customer_utils.py
git commit -m "feat(customers): AR aging + creditable-WHT YTD helpers

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Customer detail view + template

**Files:**
- Modify: `app/customers/views.py` (add `SalesInvoice` import at top; add `detail` route before `create()` at line 146)
- Create: `app/customers/templates/customers/detail.html`
- Test: `tests/integration/test_customer_detail.py`

**Interfaces:**
- Consumes: `compute_ar_aging`, `compute_creditable_wht_ytd` (Task 1); `SalesInvoice` (`app/sales_invoices/models.py`); existing `customers_bp`, `Customer`.
- Produces: endpoint `customers.detail` (`GET /customers/<int:id>`), accepting `?tab=overview|invoices`, and (invoices tab) `?date_from`, `?date_to`, `?status`, `?page`. Renders `customers/detail.html`. Links to `sales_invoices.view` and `customers.edit`.

- [ ] **Step 1: Write the failing test**

Create `tests/integration/test_customer_detail.py`:

```python
"""Integration tests for the customer detail page."""
from datetime import timedelta
from decimal import Decimal

import pytest

from app.utils import ph_now
from app.customers.models import Customer
from app.sales_invoices.models import SalesInvoice


def _customer(db_session, code='C001'):
    c = Customer(code=code, name='Acme Trading', tin='123-456-789-000',
                 payment_terms='Net 30', is_active=True)
    db_session.add(c)
    db_session.commit()
    return c


def _invoice(db_session, customer, number, status='posted', balance='1000.00',
             days_to_due=10):
    inv = SalesInvoice(
        invoice_number=number,
        invoice_date=ph_now().date(),
        due_date=ph_now().date() + timedelta(days=days_to_due),
        customer_id=customer.id,
        customer_name=customer.name,
        status=status,
        subtotal=Decimal('1120.00'),
        vat_amount=Decimal('120.00'),
        withholding_tax_amount=Decimal('20.00'),
        total_amount=Decimal('1100.00'),
        balance=Decimal(balance),
    )
    db_session.add(inv)
    db_session.commit()
    return inv


@pytest.mark.integration
def test_detail_overview_renders_for_accountant(client, db_session, accountant_user,
                                                 login_user):
    c = _customer(db_session)
    login_user(client, 'accountant', 'accountant123')

    resp = client.get(f'/customers/{c.id}')

    assert resp.status_code == 200
    body = resp.data.decode()
    assert 'Acme Trading' in body
    assert 'AR Aging' in body
    assert 'Creditable WHT' in body


@pytest.mark.integration
def test_detail_overview_renders_for_admin(client, db_session, admin_user, login_user):
    c = _customer(db_session)
    login_user(client, 'admin', 'admin123')

    resp = client.get(f'/customers/{c.id}?tab=overview')

    assert resp.status_code == 200


@pytest.mark.integration
def test_detail_invoices_tab_lists_invoices(client, db_session, accountant_user,
                                            login_user):
    c = _customer(db_session)
    _invoice(db_session, c, 'SI-2026-06-0001')
    login_user(client, 'accountant', 'accountant123')

    resp = client.get(f'/customers/{c.id}?tab=invoices')

    assert resp.status_code == 200
    assert 'SI-2026-06-0001' in resp.data.decode()


@pytest.mark.integration
def test_detail_invoices_status_filter(client, db_session, accountant_user, login_user):
    c = _customer(db_session)
    _invoice(db_session, c, 'SI-POSTED', status='posted')
    _invoice(db_session, c, 'SI-DRAFT', status='draft')
    login_user(client, 'accountant', 'accountant123')

    resp = client.get(f'/customers/{c.id}?tab=invoices&status=draft')

    body = resp.data.decode()
    assert 'SI-DRAFT' in body
    assert 'SI-POSTED' not in body


@pytest.mark.integration
def test_detail_404_for_unknown_customer(client, db_session, accountant_user, login_user):
    login_user(client, 'accountant', 'accountant123')
    resp = client.get('/customers/99999')
    assert resp.status_code == 404
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/integration/test_customer_detail.py -v`
Expected: FAIL — the overview/invoices assertions fail (route resolves to nothing or 404 for a real id) because `customers.detail` does not exist yet.

- [ ] **Step 3a: Add the `SalesInvoice` import**

In `app/customers/views.py`, after the existing model imports (the block ending at line 11 `from app.customers.forms import CustomerForm`), add:

```python
from app.sales_invoices.models import SalesInvoice
```

- [ ] **Step 3b: Add the `detail` route**

In `app/customers/views.py`, immediately **before** the line `@customers_bp.route('/customers/create', methods=['GET', 'POST'])` (line 146), insert:

```python
@customers_bp.route('/customers/<int:id>')
@login_required
def detail(id):
    """Customer detail: Overview (info + AR aging + creditable WHT YTD) and
    Invoices tabs. Read view — mirrors vendors.detail (no role gate, no audit)."""
    customer = Customer.query.get_or_404(id)
    tab = request.args.get('tab', 'overview')
    total_invoices = SalesInvoice.query.filter_by(customer_id=id).count()

    if tab == 'invoices':
        from datetime import date as date_type
        page = request.args.get('page', 1, type=int)
        date_from_str = request.args.get('date_from', '')
        date_to_str = request.args.get('date_to', '')
        status_filter = request.args.get('status', 'all')

        query = SalesInvoice.query.filter_by(customer_id=id)
        if date_from_str:
            try:
                query = query.filter(SalesInvoice.invoice_date >= date_type.fromisoformat(date_from_str))
            except ValueError:
                pass
        if date_to_str:
            try:
                query = query.filter(SalesInvoice.invoice_date <= date_type.fromisoformat(date_to_str))
            except ValueError:
                pass
        if status_filter and status_filter != 'all':
            query = query.filter(SalesInvoice.status == status_filter)

        pagination = query.order_by(SalesInvoice.invoice_date.desc()).paginate(
            page=page, per_page=20, error_out=False
        )
        return render_template(
            'customers/detail.html',
            customer=customer,
            tab='invoices',
            total_invoices=total_invoices,
            pagination=pagination,
            date_from=date_from_str,
            date_to=date_to_str,
            status_filter=status_filter,
        )
    else:
        from app.customers.utils import compute_ar_aging, compute_creditable_wht_ytd
        aging = compute_ar_aging(customer.id)
        wht_ytd = compute_creditable_wht_ytd(customer.id)
        return render_template(
            'customers/detail.html',
            customer=customer,
            tab='overview',
            total_invoices=total_invoices,
            aging=aging,
            wht_ytd=wht_ytd,
        )
```

- [ ] **Step 3c: Create the template**

Create `app/customers/templates/customers/detail.html`:

```html
{% extends "base.html" %}

{% block title %}{{ customer.name }} — Customer{% endblock %}
{% block page_title %}{{ customer.name }}{% endblock %}

{% block content %}

<!-- Header: code/status + Edit button -->
<div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:16px;">
    <div style="display:flex; align-items:center; gap:12px;">
        <span style="color:var(--text-2); font-size:14px; font-weight:500;">{{ customer.code }}</span>
        <span class="badge {% if customer.is_active %}badge-success{% else %}badge-inactive{% endif %}">
            {{ 'Active' if customer.is_active else 'Inactive' }}
        </span>
    </div>
    {% if current_user.role in ['accountant', 'admin'] %}
    <a href="{{ url_for('customers.edit', id=customer.id) }}" class="btn btn-primary btn-sm">Edit Customer</a>
    {% endif %}
</div>

<!-- Tab bar -->
<div class="customer-tab-bar">
    <a href="{{ url_for('customers.detail', id=customer.id, tab='overview') }}"
       class="customer-tab {% if tab == 'overview' %}active{% endif %}">Overview</a>
    <a href="{{ url_for('customers.detail', id=customer.id, tab='invoices') }}"
       class="customer-tab {% if tab == 'invoices' %}active{% endif %}">Invoices ({{ total_invoices }})</a>
</div>

{% if tab == 'overview' %}
<!-- ── OVERVIEW TAB ── -->
<div class="customer-overview-grid">

    <!-- Left: Customer Info -->
    <div class="card">
        <div class="card-body">
            <h4 style="margin:0 0 16px 0; font-size:15px; font-weight:600;">Customer Information</h4>
            <table class="customer-info-table">
                <tr><td>Code</td><td><strong>{{ customer.code }}</strong></td></tr>
                <tr><td>Name</td><td>{{ customer.name }}</td></tr>
                <tr><td>TIN</td><td>{{ customer.tin or '—' }}</td></tr>
                <tr><td>Contact</td><td>{{ customer.contact_person or '—' }}</td></tr>
                <tr><td>Phone</td><td>{{ customer.phone or '—' }}</td></tr>
                <tr><td>Email</td><td>{{ customer.email or '—' }}</td></tr>
                <tr><td>Address</td><td>{{ customer.address or '—' }}</td></tr>
                <tr><td>Postal Code</td><td>{{ customer.postal_code or '—' }}</td></tr>
                <tr><td>Payment Terms</td><td>{{ customer.payment_terms or '—' }}</td></tr>
                <tr>
                    <td>Default VAT</td>
                    <td>
                        {% if customer.default_vat_category %}
                        <span class="badge badge-vat">{{ customer.default_vat_category }}</span>
                        {% else %}—{% endif %}
                    </td>
                </tr>
                <tr>
                    <td>Default WHT</td>
                    <td>
                        {% for wt in customer.withholding_taxes %}
                        <span class="badge badge-wt">{{ wt.code }}</span>
                        {% else %}—{% endfor %}
                    </td>
                </tr>
            </table>
        </div>
    </div>

    <!-- Right: AR Aging + Creditable WHT YTD -->
    <div style="display:flex; flex-direction:column; gap:20px;">

        <div class="card">
            <div class="card-body">
                <h4 style="margin:0 0 16px 0; font-size:15px; font-weight:600;">AR Aging (Posted Invoices)</h4>
                <table class="customer-info-table">
                    <tr><td>Current (not yet due)</td><td class="amount-cell">₱{{ '{:,.2f}'.format(aging['current']) }}</td></tr>
                    <tr><td>1–30 days overdue</td><td class="amount-cell">₱{{ '{:,.2f}'.format(aging['1_30']) }}</td></tr>
                    <tr><td>31–60 days overdue</td><td class="amount-cell">₱{{ '{:,.2f}'.format(aging['31_60']) }}</td></tr>
                    <tr><td>61–90 days overdue</td><td class="amount-cell">₱{{ '{:,.2f}'.format(aging['61_90']) }}</td></tr>
                    <tr><td>90+ days overdue</td><td class="amount-cell" style="color:var(--red);">₱{{ '{:,.2f}'.format(aging['90_plus']) }}</td></tr>
                    <tr class="aging-total-row">
                        <td><strong>Total Outstanding</strong></td>
                        <td class="amount-cell"><strong>₱{{ '{:,.2f}'.format(aging['total']) }}</strong></td>
                    </tr>
                </table>
            </div>
        </div>

        <div class="card">
            <div class="card-body">
                <h4 style="margin:0 0 16px 0; font-size:15px; font-weight:600;">Creditable WHT (BIR 2307) YTD</h4>
                {% if wht_ytd %}
                <table class="customer-info-table">
                    {% for row in wht_ytd %}
                    <tr>
                        <td>{{ row.code }} — {{ row.name }}</td>
                        <td class="amount-cell">₱{{ '{:,.2f}'.format(row.total) }}</td>
                    </tr>
                    {% endfor %}
                </table>
                {% else %}
                <p style="color:var(--text-2); font-style:italic; margin:0;">No creditable WHT recorded this calendar year.</p>
                {% endif %}
            </div>
        </div>
    </div>
</div>

{% else %}
<!-- ── INVOICES TAB ── -->
<div style="margin-top:16px;">
    <form method="GET" action="{{ url_for('customers.detail', id=customer.id) }}"
          style="display:flex; gap:12px; align-items:flex-end; margin-bottom:16px; flex-wrap:wrap;">
        <input type="hidden" name="tab" value="invoices">
        <div>
            <label style="font-size:13px; font-weight:500; display:block; margin-bottom:4px;">Date From</label>
            <input type="date" name="date_from" value="{{ date_from }}"
                   class="form-control form-control-sm" style="width:160px;">
        </div>
        <div>
            <label style="font-size:13px; font-weight:500; display:block; margin-bottom:4px;">Date To</label>
            <input type="date" name="date_to" value="{{ date_to }}"
                   class="form-control form-control-sm" style="width:160px;">
        </div>
        <div>
            <label style="font-size:13px; font-weight:500; display:block; margin-bottom:4px;">Status</label>
            <select name="status" class="form-control form-control-sm" style="width:150px;">
                <option value="all" {% if status_filter == 'all' %}selected{% endif %}>All Statuses</option>
                <option value="draft" {% if status_filter == 'draft' %}selected{% endif %}>Draft</option>
                <option value="posted" {% if status_filter == 'posted' %}selected{% endif %}>Posted</option>
                <option value="partially_paid" {% if status_filter == 'partially_paid' %}selected{% endif %}>Partially Paid</option>
                <option value="paid" {% if status_filter == 'paid' %}selected{% endif %}>Paid</option>
                <option value="voided" {% if status_filter == 'voided' %}selected{% endif %}>Voided</option>
                <option value="cancelled" {% if status_filter == 'cancelled' %}selected{% endif %}>Cancelled</option>
            </select>
        </div>
        <button type="submit" class="btn btn-primary btn-sm" style="align-self:flex-end;">Filter</button>
        <a href="{{ url_for('customers.detail', id=customer.id, tab='invoices') }}"
           class="btn btn-secondary btn-sm" style="align-self:flex-end;">Clear</a>
    </form>

    <div class="card">
        <div class="card-body" style="padding:0;">
            <table class="data-table">
                <thead>
                    <tr>
                        <th>INVOICE #</th>
                        <th>INVOICE DATE</th>
                        <th>DUE DATE</th>
                        <th style="text-align:right;">SUBTOTAL</th>
                        <th style="text-align:right;">OUTPUT VAT</th>
                        <th style="text-align:right;">WHT</th>
                        <th style="text-align:right;">NET AMOUNT</th>
                        <th>STATUS</th>
                    </tr>
                </thead>
                <tbody>
                    {% for inv in pagination.items %}
                    <tr>
                        <td>
                            <a href="{{ url_for('sales_invoices.view', id=inv.id) }}"
                               style="color:var(--blue); text-decoration:none;">
                                {{ inv.invoice_number }}
                            </a>
                        </td>
                        <td>{{ inv.invoice_date.strftime('%b %d, %Y') }}</td>
                        <td>{{ inv.due_date.strftime('%b %d, %Y') }}</td>
                        <td style="text-align:right;">₱{{ '{:,.2f}'.format(inv.subtotal) }}</td>
                        <td style="text-align:right;">₱{{ '{:,.2f}'.format(inv.vat_amount) }}</td>
                        <td style="text-align:right; color:var(--red);">
                            {% if inv.withholding_tax_amount > 0 %}
                            -₱{{ '{:,.2f}'.format(inv.withholding_tax_amount) }}
                            {% else %}—{% endif %}
                        </td>
                        <td style="text-align:right; font-weight:600;">₱{{ '{:,.2f}'.format(inv.total_amount) }}</td>
                        <td>
                            {% set inv_badge = {'partially_paid': 'partial', 'voided': 'void'} %}
                            <span class="badge badge-{{ inv_badge.get(inv.status, inv.status) }}">{{ inv.status | replace('_', ' ') | title }}</span>
                        </td>
                    </tr>
                    {% else %}
                    <tr>
                        <td colspan="8" style="text-align:center; color:var(--text-2); padding:32px; font-style:italic;">
                            No invoices found.
                        </td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
    </div>

    {% if pagination.pages > 1 %}
    <div style="display:flex; justify-content:center; align-items:center; gap:12px; margin-top:16px;">
        {% if pagination.has_prev %}
        <a href="{{ url_for('customers.detail', id=customer.id, tab='invoices', page=pagination.prev_num,
                            date_from=date_from, date_to=date_to, status=status_filter) }}"
           class="btn btn-secondary btn-sm">← Previous</a>
        {% endif %}
        <span style="font-size:14px; color:var(--text-2);">
            Page {{ pagination.page }} of {{ pagination.pages }} ({{ pagination.total }} invoices)
        </span>
        {% if pagination.has_next %}
        <a href="{{ url_for('customers.detail', id=customer.id, tab='invoices', page=pagination.next_num,
                            date_from=date_from, date_to=date_to, status=status_filter) }}"
           class="btn btn-primary btn-sm">Next →</a>
        {% endif %}
    </div>
    {% endif %}
</div>
{% endif %}

<style>
.customer-tab-bar {
    display: flex;
    border-bottom: 2px solid var(--border);
    margin-bottom: 20px;
}
.customer-tab {
    padding: 10px 20px;
    font-size: 14px;
    font-weight: 500;
    color: var(--text-2);
    text-decoration: none;
    border-bottom: 2px solid transparent;
    margin-bottom: -2px;
    transition: color 0.15s, border-color 0.15s;
}
.customer-tab:hover { color: var(--text); }
.customer-tab.active {
    color: var(--blue);
    border-bottom-color: var(--blue);
    font-weight: 600;
}
.customer-overview-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 20px;
}
.customer-info-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 14px;
}
.customer-info-table td { padding: 6px 8px; vertical-align: top; }
.customer-info-table td:first-child { color: var(--text-2); width: 40%; white-space: nowrap; }
.customer-info-table tr + tr td { border-top: 1px solid var(--border); }
.amount-cell { text-align: right; font-variant-numeric: tabular-nums; }
.aging-total-row td { border-top: 2px solid var(--border) !important; padding-top: 10px !important; }
.badge-vat  { background:#dcfce7; color:#166534; border:1px solid #bbf7d0; }
.badge-wt   { background:#dbeafe; color:#1e40af; border:1px solid #bfdbfe; }
@media (max-width: 768px) {
    .customer-overview-grid { grid-template-columns: 1fr; }
}
</style>
{% endblock %}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/integration/test_customer_detail.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add app/customers/views.py app/customers/templates/customers/detail.html tests/integration/test_customer_detail.py
git commit -m "feat(customers): detail page (overview + invoices tabs)

Mirror of the vendor detail page. Overview shows Customer Info, AR Aging,
and Creditable WHT (BIR 2307) YTD; Invoices tab is filterable + paginated.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Re-point customer-list links to the detail page

**Files:**
- Modify: `app/customers/templates/customers/list.html:50,52`
- Test: `tests/integration/test_customer_detail.py` (append one test)

**Interfaces:**
- Consumes: `customers.detail` (Task 2).
- Produces: nothing new — behavior change only (list code/name now open the detail page).

- [ ] **Step 1: Write the failing test**

Append to `tests/integration/test_customer_detail.py`:

```python
@pytest.mark.integration
def test_list_links_point_to_detail(client, db_session, accountant_user, login_user):
    c = _customer(db_session)
    login_user(client, 'accountant', 'accountant123')

    resp = client.get('/customers')

    body = resp.data.decode()
    assert f'/customers/{c.id}"' in body          # detail link present
    # the code/name cells must no longer link to the edit page
    assert f'/customers/{c.id}/edit" class="customer-link"' not in body
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/integration/test_customer_detail.py::test_list_links_point_to_detail -v`
Expected: FAIL — the code/name links still target `…/edit` with class `customer-link`.

- [ ] **Step 3: Re-point the two links**

In `app/customers/templates/customers/list.html`, change line 50 from:

```html
                    <td><a href="{{ url_for('customers.edit', id=customer.id) }}" class="customer-link"><strong>{{ customer.code }}</strong></a></td>
```
to:
```html
                    <td><a href="{{ url_for('customers.detail', id=customer.id) }}" class="customer-link"><strong>{{ customer.code }}</strong></a></td>
```

and line 52 from:

```html
                        <a href="{{ url_for('customers.edit', id=customer.id) }}" class="customer-link">{{ customer.name }}</a>
```
to:
```html
                        <a href="{{ url_for('customers.detail', id=customer.id) }}" class="customer-link">{{ customer.name }}</a>
```

(Leave the row's Edit action button — `customers.edit` at line ~89 — unchanged.)

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/integration/test_customer_detail.py -v`
Expected: PASS (6 passed).

- [ ] **Step 5: Commit**

```bash
git add app/customers/templates/customers/list.html tests/integration/test_customer_detail.py
git commit -m "feat(customers): list code/name links open detail page

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:**
- Routing & tabs → Task 2 ✓
- `compute_ar_aging` / `compute_creditable_wht_ytd` → Task 1 ✓
- Overview content (Info minus check_payee, AR aging, Creditable WHT panel) → Task 2 template ✓
- Invoices tab (columns, filter, pagination, SI link) → Task 2 template ✓
- List links re-pointed → Task 3 ✓
- Access (login-only, no audit, registry prefix) → Global Constraints + Task 2 ✓
- Tests (aging math, WHT grouping, route per role, filter/pagination, list links) → Tasks 1–3 ✓
- No model/migration changes → confirmed ✓

**Placeholder scan:** none — all steps carry full code/commands.

**Type consistency:** `compute_ar_aging` returns dict keyed `current/1_30/31_60/61_90/90_plus/total`; template reads the same keys. `compute_creditable_wht_ytd` returns `{code,name,total}`; template reads the same. View passes `customer`, `tab`, `total_invoices`, `aging`, `wht_ytd`, `pagination`, `date_from`, `date_to`, `status_filter`; template consumes exactly those. SI fields used in template (`invoice_number`, `invoice_date`, `due_date`, `subtotal`, `vat_amount`, `withholding_tax_amount`, `total_amount`, `status`) all verified against the model.

## Manual verification (after all tasks)

1. `flask run` (or it's already on :5050), log in, visit `/customers`, click a customer's name → detail page Overview renders.
2. Switch to the Invoices tab; confirm the customer's SIs list, the status filter narrows results, and an invoice # links to its SI view.
3. Confirm `₱` renders correctly (not `&#8369;`) and the page is responsive (single-column overview under 768px).
